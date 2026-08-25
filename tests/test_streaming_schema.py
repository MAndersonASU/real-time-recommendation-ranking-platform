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
