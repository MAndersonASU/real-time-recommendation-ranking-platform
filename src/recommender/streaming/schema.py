import json
import uuid
from dataclasses import asdict, dataclass
from enum import Enum

SCHEMA_VERSION = 1

# This project's own frozen scope boundary (docs/research-scenario.md)
# defines "real-time" as replayed historical events, not a live production
# feed -- every event this system ever produces carries that fact directly
# in its `source` field, rather than leaving it implicit.
REPLAY_SOURCE = "mind_historical_replay"


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

    @staticmethod
    def from_json(raw: str) -> "InteractionEvent":
        payload = json.loads(raw)
        payload["event_type"] = EventType(payload["event_type"])
        return InteractionEvent(**payload)


def make_event(
    event_type: EventType,
    user_id: str,
    item_id: str,
    impression_id: int,
    timestamp: str,
    source: str = REPLAY_SOURCE,
) -> InteractionEvent:
    return InteractionEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        schema_version=SCHEMA_VERSION,
        user_id=user_id,
        item_id=item_id,
        impression_id=impression_id,
        timestamp=timestamp,
        source=source,
    )
