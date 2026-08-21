from recommender.streaming.schema import (
    SCHEMA_VERSION,
    EventType,
    InteractionEvent,
    make_event,
)


def test_make_event_assigns_a_unique_event_id_and_the_current_schema_version():
    a = make_event(EventType.CLICK, "U1", "N1", 100, "2019-11-14 09:00:00")
    b = make_event(EventType.CLICK, "U1", "N1", 100, "2019-11-14 09:00:00")

    assert a.event_id != b.event_id
    assert a.schema_version == SCHEMA_VERSION


def test_round_trip_through_json_preserves_every_field():
    event = make_event(EventType.SKIP, "U2", "N9", 200, "2019-11-14 10:30:00")

    restored = InteractionEvent.from_json(event.to_json())

    assert restored == event
    assert restored.event_type is EventType.SKIP  # enum, not a bare string, after round-trip


def test_default_source_identifies_historical_replay_not_a_live_feed():
    event = make_event(EventType.IMPRESSION, "U3", "N4", 300, "2019-11-14 08:00:00")

    assert "replay" in event.source
