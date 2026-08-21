import json

from recommender.streaming.consumer import MAX_RECENT_ITEMS, StreamConsumer
from recommender.streaming.schema import EventType, make_event


def test_process_updates_user_state_for_a_click():
    consumer = StreamConsumer()
    event = make_event(EventType.CLICK, "U1", "N1", 1, "2019-11-15 08:00:00")

    processed = consumer.process(event.to_json())

    assert processed is True
    state = consumer.user_states["U1"]
    assert state.clicks_seen == 1
    assert list(state.recent_clicked_items) == ["N1"]


def test_process_counts_impressions_separately_from_clicks():
    consumer = StreamConsumer()
    consumer.process(make_event(EventType.IMPRESSION, "U1", "N1", 1, "t").to_json())
    consumer.process(make_event(EventType.IMPRESSION, "U1", "N2", 1, "t").to_json())
    consumer.process(make_event(EventType.CLICK, "U1", "N2", 1, "t").to_json())

    state = consumer.user_states["U1"]
    assert state.impressions_seen == 2
    assert state.clicks_seen == 1


def test_malformed_json_is_rejected_not_raised():
    consumer = StreamConsumer()

    processed = consumer.process(b"not valid json at all {{{")

    assert processed is False
    assert consumer.counters.malformed_rejected == 1
    assert consumer.counters.total_processed == 0


def test_wrong_schema_version_is_rejected():
    consumer = StreamConsumer()
    event = make_event(EventType.CLICK, "U1", "N1", 1, "t")
    payload = json.loads(event.to_json())
    payload["schema_version"] = 999
    tampered = json.dumps(payload)

    processed = consumer.process(tampered)

    assert processed is False
    assert consumer.counters.malformed_rejected == 1


def test_duplicate_event_id_is_skipped_on_second_delivery():
    consumer = StreamConsumer()
    event = make_event(EventType.CLICK, "U1", "N1", 1, "t")
    raw = event.to_json()

    first = consumer.process(raw)
    second = consumer.process(raw)  # same event_id, redelivered

    assert first is True
    assert second is False
    assert consumer.counters.duplicates_skipped == 1
    assert consumer.user_states["U1"].clicks_seen == 1  # not double-counted


def test_recent_clicked_items_is_bounded_to_max_recent_items():
    consumer = StreamConsumer()
    for i in range(MAX_RECENT_ITEMS + 5):
        event = make_event(EventType.CLICK, "U1", f"N{i}", 1, "t")
        consumer.process(event.to_json())

    state = consumer.user_states["U1"]
    assert len(state.recent_clicked_items) == MAX_RECENT_ITEMS
    assert list(state.recent_clicked_items)[-1] == f"N{MAX_RECENT_ITEMS + 4}"  # most recent kept


def test_different_users_are_tracked_independently():
    consumer = StreamConsumer()
    consumer.process(make_event(EventType.CLICK, "U1", "N1", 1, "t").to_json())
    consumer.process(make_event(EventType.CLICK, "U2", "N2", 2, "t").to_json())

    assert consumer.user_states["U1"].clicks_seen == 1
    assert consumer.user_states["U2"].clicks_seen == 1
    assert consumer.counters.distinct_users == {"U1", "U2"}
    assert consumer.counters.distinct_items == {"N1", "N2"}


def test_monitoring_counters_track_events_by_type():
    consumer = StreamConsumer()
    consumer.process(make_event(EventType.IMPRESSION, "U1", "N1", 1, "t").to_json())
    consumer.process(make_event(EventType.CLICK, "U1", "N1", 1, "t").to_json())
    consumer.process(make_event(EventType.SKIP, "U1", "N2", 1, "t").to_json())

    assert consumer.counters.events_by_type == {"impression": 1, "click": 1, "skip": 1}
    assert consumer.counters.total_processed == 3
