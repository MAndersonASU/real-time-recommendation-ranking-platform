import pytest

from recommender.streaming.schema import (
    SCHEMA_VERSION,
    EventType,
    InteractionEvent,
    make_event,
)


def test_make_event_derives_a_stable_id_from_the_events_own_fields():
    """Replay is re-runnable by design, so the same historical
    interaction must produce the same event id every time. A random id
    made a re-run look like entirely new traffic, which no amount of
    duplicate detection downstream could recognise -- the consumer could
    only ever catch a redelivery within one run, never a repeated replay.
    """
    a = make_event(EventType.CLICK, "U1", "N1", 100, "2019-11-14 09:00:00")
    b = make_event(EventType.CLICK, "U1", "N1", 100, "2019-11-14 09:00:00")

    assert a.event_id == b.event_id
    assert a.schema_version == SCHEMA_VERSION


def test_make_event_ids_differ_when_any_identifying_field_differs():
    base = ("U1", "N1", 100, "2019-11-14 09:00:00")
    original = make_event(EventType.CLICK, *base)

    variants = [
        make_event(EventType.IMPRESSION, *base),
        make_event(EventType.CLICK, "U2", "N1", 100, "2019-11-14 09:00:00"),
        make_event(EventType.CLICK, "U1", "N2", 100, "2019-11-14 09:00:00"),
        make_event(EventType.CLICK, "U1", "N1", 101, "2019-11-14 09:00:00"),
        make_event(EventType.CLICK, "U1", "N1", 100, "2019-11-14 09:00:01"),
    ]

    ids = {v.event_id for v in variants}
    assert original.event_id not in ids
    assert len(ids) == len(variants), "each identifying field must affect the id"


def test_a_caller_can_supply_its_own_event_id_for_genuinely_new_traffic():
    """A live interaction is not a replay of a recorded one, so a caller
    representing real new traffic can still assign its own identity.
    """
    event = make_event(
        EventType.CLICK, "U1", "N1", 100, "2019-11-14 09:00:00", event_id="live-abc"
    )

    assert event.event_id == "live-abc"


def test_round_trip_through_json_preserves_every_field():
    event = make_event(EventType.SKIP, "U2", "N9", 200, "2019-11-14 10:30:00")

    restored = InteractionEvent.from_json(event.to_json())

    assert restored == event
    assert restored.event_type is EventType.SKIP  # enum, not a bare string, after round-trip


def test_default_source_identifies_historical_replay_not_a_live_feed():
    event = make_event(EventType.IMPRESSION, "U3", "N4", 300, "2019-11-14 08:00:00")

    assert "replay" in event.source


# --- Boundary validation ---------------------------------------------
#
# Parsing previously accepted anything JSON-shaped. Each field below
# reaches a Redis key, a log line or a downstream assumption, so an
# unusable value is rejected at the boundary rather than surfacing later
# as a corrupted key or an unbounded write.

def _payload(**overrides):
    import json

    event = make_event(EventType.CLICK, "U1", "N1", 5, "2019-11-14T08:00:00")
    data = json.loads(event.to_json())
    data.update(overrides)
    return json.dumps(data)


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("empty user id", {"user_id": ""}),
        ("oversized user id", {"user_id": "U" * 129}),
        ("whitespace in id", {"user_id": "U 1"}),
        ("control character in id", {"user_id": "U\x001"}),
        ("empty item id", {"item_id": ""}),
        ("boolean schema version", {"schema_version": True}),
        ("boolean impression id", {"impression_id": True}),
        ("negative impression id", {"impression_id": -1}),
        ("arbitrary source", {"source": "attacker-supplied"}),
        ("non-datetime timestamp", {"timestamp": "not-a-time"}),
        ("non-uuid event id", {"event_id": "not-a-uuid"}),
        ("unexpected field", {"injected": "payload"}),
    ],
)
def test_invalid_event_payloads_are_rejected(label, overrides):
    with pytest.raises((ValueError, TypeError, KeyError)):
        InteractionEvent.from_json(_payload(**overrides))


def test_a_boolean_is_not_accepted_as_an_integer():
    """bool subclasses int in Python, so `isinstance(True, int)` is True
    and a boolean would otherwise pass an integer check silently.
    """
    with pytest.raises(TypeError, match="schema_version must be an integer"):
        InteractionEvent.from_json(_payload(schema_version=True))


def test_mind_style_space_separated_timestamps_are_accepted():
    """MIND's own timestamps are not RFC3339-formatted, so both forms
    must parse -- what is rejected is a string that is not a datetime.
    """
    event = InteractionEvent.from_json(_payload(timestamp="2019-11-14 08:00:00"))

    assert event.timestamp == "2019-11-14 08:00:00"


def test_a_valid_event_still_round_trips():
    original = make_event(EventType.CLICK, "U1", "N1", 5, "2019-11-14T08:00:00")

    restored = InteractionEvent.from_json(original.to_json())

    assert restored == original


# --- TIMESTAMP-CONTRACT-64: a non-replay source needs a real RFC3339
# timestamp, not merely something datetime.fromisoformat happens to parse ---


def test_a_replay_source_still_accepts_mind_style_naive_timestamps():
    # REPLAY_SOURCE (the default `source`) is exactly the one place
    # MIND's own naive, dataset-local timestamp shape is legitimate.
    event = InteractionEvent.from_json(_payload(timestamp="2019-11-14 08:00:00"))

    assert event.timestamp == "2019-11-14 08:00:00"


def test_a_non_replay_source_rejects_a_naive_timestamp():
    """Regression test for a real bug, found by audit: the validator
    accepted a naive timestamp (no timezone offset) for every source,
    including one that is not a replay of historical MIND data, while
    its own error message claimed "must be an RFC3339 datetime" -- RFC3339
    requires an offset, so a naive string was never actually RFC3339.
    Fails on the pre-fix code (a naive string passes regardless of
    source) and passes once a non-replay source is held to the real
    standard its error message already claimed.
    """
    with pytest.raises(ValueError, match="RFC3339"):
        InteractionEvent.from_json(
            _payload(source="synthetic_test", timestamp="2019-11-14T08:00:00")
        )


def test_a_non_replay_source_accepts_a_real_timezone_aware_timestamp():
    event = InteractionEvent.from_json(
        _payload(source="synthetic_test", timestamp="2019-11-14T08:00:00+00:00")
    )

    assert event.timestamp == "2019-11-14T08:00:00+00:00"


def test_a_non_replay_source_accepts_a_trailing_z_offset():
    event = InteractionEvent.from_json(
        _payload(source="synthetic_test", timestamp="2019-11-14T08:00:00Z")
    )

    assert event.timestamp == "2019-11-14T08:00:00Z"


# --- TIMESTAMP-CONTRACT-64 follow-up: _is_rfc3339 must reject anything
# datetime.fromisoformat parses that RFC3339's own grammar does not ---


@pytest.mark.parametrize(
    ("label", "timestamp"),
    [
        ("space instead of T", "2019-11-14 08:00:00+00:00"),
        ("seconds omitted", "2019-11-14T08:00+00:00"),
        ("lowercase t separator", "2019-11-14t08:00:00+00:00"),
        ("lowercase z offset", "2019-11-14T08:00:00z"),
        ("missing offset entirely", "2019-11-14T08:00:00"),
        ("offset with no colon", "2019-11-14T08:00:00+0000"),
        ("offset with no minutes", "2019-11-14T08:00:00+00"),
        ("date-only, no time", "2019-11-14"),
        ("ordinal date form", "2019-318T08:00:00Z"),
        ("impossible month", "2019-13-01T08:00:00Z"),
        ("impossible hour", "2019-11-14T25:00:00Z"),
        ("impossible day", "2019-02-30T08:00:00Z"),
        ("offset minute 60, out of range", "2019-11-14T08:00:00+00:60"),
        ("offset minute 99, out of range", "2019-11-14T08:00:00+00:99"),
        ("negative offset minute 60, out of range", "2019-11-14T08:00:00-00:60"),
        ("offset hour 24, out of range", "2019-11-14T08:00:00+24:00"),
        ("leap second, not representable at all", "2019-11-14T23:59:60Z"),
    ],
)
def test_non_replay_source_rejects_forms_outside_canonical_profile(label, timestamp):
    """Regression test for two real bugs, both found by audit.

    First round: `_is_rfc3339` only checked that `datetime.fromisoformat`
    parsed the value and found a timezone -- but `fromisoformat` accepts
    plenty of real ISO 8601 forms this project's canonical profile does
    not accept. Some of those forms are genuinely excluded by RFC3339's
    own grammar (a space instead of "T", omitted seconds). Others --
    a lowercase "t"/"z" -- RFC3339 itself permits as a case-insensitive
    alternate; this project's own narrower profile is what excludes
    them, not RFC3339. (This test was previously named
    `test_non_replay_source_rejects_iso8601_forms_outside_rfc3339`,
    which read as a claim about RFC3339 itself rather than about this
    project's own canonical profile -- corrected along with the
    docstrings and error messages that made the same conflation.)

    Second round: even after a structural regex was added, the offset's
    own hour and minute weren't range-checked -- `"+00:60"` (minute 60,
    out of RFC3339's 00-59 range) reached `fromisoformat`, which
    silently normalizes it to `"+01:00"` via plain timedelta arithmetic
    instead of rejecting it, so it passed anyway. A leap second
    (`":60"` as the *seconds* field) is separately rejected here too --
    RFC3339's grammar permits it, but Python's `datetime` cannot
    represent one at all, so this project's canonical profile does not
    accept it either, and says so in `_is_rfc3339`'s own docstring.

    Fails on either pre-fix version (all of these parse) and passes
    once the regex enforces this project's canonical profile *and*
    range-checks the offset fields, with `fromisoformat` still catching
    a structurally valid but calendar-impossible date or time.
    """
    with pytest.raises(ValueError, match="RFC3339"):
        InteractionEvent.from_json(_payload(source="synthetic_test", timestamp=timestamp))


def test_non_replay_source_accepts_every_real_rfc3339_shape():
    for timestamp in [
        "2019-11-14T08:00:00Z",
        "2019-11-14T08:00:00+00:00",
        "2019-11-14T08:00:00-05:00",
        "2019-11-14T08:00:00.123Z",
        "2019-11-14T08:00:00.123456+00:00",
    ]:
        event = InteractionEvent.from_json(_payload(source="synthetic_test", timestamp=timestamp))
        assert event.timestamp == timestamp
