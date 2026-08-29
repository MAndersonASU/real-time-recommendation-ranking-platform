import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum

SCHEMA_VERSION = 1

# This project's own frozen scope boundary (docs/research-scenario.md)
# defines "real-time" as replayed historical events, not a live production
# feed -- every event this system ever produces carries that fact directly
# in its `source` field, rather than leaving it implicit.
REPLAY_SOURCE = "mind_historical_replay"

# Enumerated rather than free-form: `source` is written to logs and used
# to reason about provenance, so an arbitrary caller-supplied string is
# both a storage and an interpretation hazard.
ALLOWED_SOURCES = frozenset({REPLAY_SOURCE, "synthetic_test"})

# Bounded and restricted for the same reasons as the API's user id: these
# reach Redis keys and log lines.
MAX_IDENTIFIER_LENGTH = 128
IDENTIFIER_PATTERN = re.compile(rf"^[A-Za-z0-9._:-]{{1,{MAX_IDENTIFIER_LENGTH}}}$")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


# This project's canonical RFC3339 profile -- a deliberately narrower,
# fully-specified subset of RFC3339 (section 5.6), not the full
# permissive grammar. Every restriction below is enforced here, stated
# in _is_rfc3339's docstring, echoed in InteractionEvent.validate's
# error message, and exercised by tests/test_streaming_schema.py --
# code, error message, docs and tests describe the same contract, and
# if the contract ever changes, all four move together:
#
#   - a literal, uppercase "T" date/time separator: not a space, not
#     lowercase "t". RFC3339 itself permits a space or "t" as
#     ISO-8601-derived alternates; this profile picks the one
#     unambiguous machine-readable shape rather than accepting all of
#     them, since a live producer this project controls has no reason
#     to emit anything else.
#   - mandatory seconds (`time-second` is not optional in RFC3339's
#     `partial-time`), no leap second: RFC3339's grammar permits a
#     ":60" second for a leap second, but Python's `datetime` cannot
#     represent one at all (`fromisoformat` rejects it, same as any
#     other out-of-range value) -- this profile does not accept one
#     either, rather than silently truncating or misparsing it. A
#     genuinely leap-second-aware live feed is out of scope for what
#     this project's serving path needs.
#   - a mandatory offset: literal uppercase "Z", or a numeric
#     "+HH:MM"/"-HH:MM" with the hour and minute each *range*-checked
#     (00-23, 00-59), not merely two digits. `datetime.fromisoformat`
#     does not enforce that range on an offset -- it treats the offset
#     as a plain timedelta, so "+00:60" silently normalizes to
#     "+01:00" instead of being rejected, found by direct
#     reproduction, not assumed. Not lowercase "z", not a bare "+00"
#     or "+0000".
#   - fractional seconds are optional, per `time-secfrac`.
_OFFSET_HOUR = r"(?:[01]\d|2[0-3])"  # 00-23
_OFFSET_MINUTE = r"[0-5]\d"  # 00-59
_RFC3339_RE = re.compile(
    rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}(\.\d+)?"
    rf"(Z|[+-]{_OFFSET_HOUR}:{_OFFSET_MINUTE})$"
)


def _is_rfc3339(value: str) -> bool:
    """This project's canonical RFC3339 profile, not the full permissive
    grammar and not merely a string `datetime.fromisoformat` happens to
    accept. Three ways `fromisoformat` alone is not this profile:

    - It also parses MIND's own space-separated, offset-less shape and
      several ISO 8601 forms RFC3339 itself excludes (omitted seconds,
      a lowercase "t"/"z") -- rejected here by the structural regex
      above, which runs first.
    - It silently normalizes an out-of-range offset minute/hour
      ("+00:60" becomes "+01:00") instead of rejecting it -- the regex
      above range-checks the offset's own hour and minute instead of
      accepting any two digits.
    - `fromisoformat` still runs *after* the regex, on values that
      already passed it, to reject a structurally valid but
      calendar-impossible date or time (month 13, hour 25, ...), which
      the regex's fixed-width date/main-time digit groups cannot catch
      by themselves.

    Required for a live event's own timestamp (`InteractionEvent.validate`,
    any `source` other than `REPLAY_SOURCE`); `_is_dataset_local_timestamp`
    below is the deliberately more permissive check for a replayed one.
    """
    if not _RFC3339_RE.match(value):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, AttributeError):
        return False
    return parsed.tzinfo is not None


def _is_dataset_local_timestamp(value: str) -> bool:
    """MIND's own timestamp format: naive, space-separated, and of an
    unknown timezone -- MIND does not document it
    (`docs/engineering-review-register.md`'s FEATURE-TIMEZONE-20). Not
    RFC3339 (no offset, wrong separator) and not named or described as
    RFC3339 anywhere this is used; what is rejected is a string that is
    not a datetime at all. Deliberately as permissive as `_is_rfc3339`
    used to be, for the one source (`REPLAY_SOURCE`) that legitimately
    carries this shape.
    """
    try:
        datetime.fromisoformat(value)
    except (ValueError, AttributeError):
        return False
    return True


class EventType(str, Enum):
    IMPRESSION = "impression"
    VIEW = "view"
    CLICK = "click"
    SKIP = "skip"


@dataclass(frozen=True)
class InteractionEvent:
    """One user-item interaction, self-contained enough to be sent as a
    single Kafka message. `event_id` identifies this specific event (what
    duplicate-detection checks against); `schema_version` identifies the
    event *format*, so a future consumer can detect a layout change
    instead of silently misreading an old or new message.

    MIND provides direct signal for IMPRESSION and CLICK, and SKIP is
    derived from an impression's own clicked=0 flag -- no new information
    invented, just a name given to a pattern already in the data. VIEW is
    a real, defined event type with no MIND signal behind it at all: this
    dataset has no notion of "seen but not clicked," so nothing in this
    project ever produces a VIEW event. The type stays in the schema
    because a real event schema should describe every interaction a
    production system might one day emit, not just the ones one dataset
    happens to support.
    """

    event_id: str
    event_type: EventType
    schema_version: int
    user_id: str
    item_id: str
    impression_id: int
    timestamp: str
    source: str

    def to_json(self) -> str:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return json.dumps(payload)

    def validate(self) -> None:
        """Rejects a structurally valid message whose fields are not
        usable.

        Parsing previously accepted anything JSON-shaped: an empty or
        arbitrarily long identifier, a boolean where an integer was
        expected, a free-form source, and any string at all as a
        timestamp. Every one of those reaches a Redis key, a log line or
        a downstream assumption, so they are checked at the boundary
        rather than surfacing later as a corrupted key or an unbounded
        write.
        """
        for label, value in (("user_id", self.user_id), ("item_id", self.item_id)):
            if not isinstance(value, str) or not IDENTIFIER_PATTERN.match(value):
                raise ValueError(
                    f"{label} must be 1-{MAX_IDENTIFIER_LENGTH} characters of "
                    f"[A-Za-z0-9._:-], got {value!r}"
                )

        if not isinstance(self.event_id, str) or not _is_uuid(self.event_id):
            raise ValueError(f"event_id must be a UUID, got {self.event_id!r}")

        # bool is a subclass of int in Python, so `isinstance(True, int)`
        # is True and a boolean would otherwise pass as a version or an
        # impression id.
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError(f"schema_version must be an integer, got {self.schema_version!r}")
        if isinstance(self.impression_id, bool) or not isinstance(self.impression_id, int):
            raise TypeError(f"impression_id must be an integer, got {self.impression_id!r}")
        if self.impression_id < 0:
            raise ValueError(f"impression_id must be non-negative, got {self.impression_id}")

        if self.source not in ALLOWED_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(ALLOWED_SOURCES)}, got {self.source!r}"
            )

        if not isinstance(self.timestamp, str):
            raise TypeError(f"timestamp must be a string, got {self.timestamp!r}")
        # A replayed MIND event legitimately carries MIND's own naive,
        # dataset-local timestamp shape; anything else claims to be a
        # live event's own timestamp and must actually be one -- a real,
        # timezone-aware RFC3339 datetime, not merely something
        # `datetime.fromisoformat` happens to parse.
        if self.source == REPLAY_SOURCE:
            if not _is_dataset_local_timestamp(self.timestamp):
                raise ValueError(
                    f"timestamp must be a parseable datetime, got {self.timestamp!r}"
                )
        elif not _is_rfc3339(self.timestamp):
            raise ValueError(
                f"timestamp must be RFC3339 (this project's canonical profile: "
                f"uppercase 'T'/'Z', a range-checked +HH:MM/-HH:MM offset if not "
                f"'Z', mandatory seconds, no leap second) for source "
                f"{self.source!r}, got {self.timestamp!r}"
            )

    @staticmethod
    def from_json(raw: str) -> "InteractionEvent":
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError("event payload must be a JSON object")
        unexpected = set(payload) - _EVENT_FIELDS
        if unexpected:
            raise ValueError(f"unexpected event fields: {sorted(unexpected)}")
        payload["event_type"] = EventType(payload["event_type"])
        event = InteractionEvent(**payload)
        event.validate()
        return event


_EVENT_FIELDS = {
    "event_id", "event_type", "schema_version", "user_id",
    "item_id", "impression_id", "timestamp", "source",
}


def stable_event_id(
    event_type: EventType,
    user_id: str,
    item_id: str,
    impression_id: int,
    timestamp: str,
    source: str,
) -> str:
    """A deterministic id derived from the immutable fields identifying
    one historical interaction.

    Replay is re-runnable by design, and a random id would make the same
    historical event look like a brand new one on every run -- so the
    consumer's duplicate detection could never recognise a repeated
    replay, only a redelivery within a single run. Deriving the id from
    the source record instead means replaying the same day twice is
    idempotent for the same reason a redelivery is.

    Uses `uuid5`, which is a namespaced SHA-1 of the name, so the value
    is a real UUID and stays stable across processes and machines.
    """
    name = "|".join([source, event_type.value, user_id, item_id, str(impression_id), timestamp])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def make_event(
    event_type: EventType,
    user_id: str,
    item_id: str,
    impression_id: int,
    timestamp: str,
    source: str = REPLAY_SOURCE,
    event_id: str | None = None,
) -> InteractionEvent:
    """`event_id` defaults to a deterministic id derived from this
    event's own immutable fields (`stable_event_id`). A caller
    representing a genuinely new, live interaction -- rather than a
    replay of a recorded one -- can pass its own id instead.
    """
    return InteractionEvent(
        event_id=event_id
        or stable_event_id(event_type, user_id, item_id, impression_id, timestamp, source),
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        user_id=user_id,
        item_id=item_id,
        impression_id=impression_id,
        timestamp=timestamp,
        source=source,
    )
