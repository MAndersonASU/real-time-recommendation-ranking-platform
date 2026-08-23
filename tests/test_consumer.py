import json
from unittest.mock import patch

from confluent_kafka import KafkaError, KafkaException

from recommender.streaming.consumer import MAX_RECENT_ITEMS, StreamConsumer, run_consumer
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


class _FakeMessage:
    def __init__(self, value: bytes):
        self._value = value

    def error(self):
        return None

    def value(self):
        return self._value


class _FailingCommitConsumer:
    """Mimics confluent_kafka.Consumer just enough for run_consumer:
    yields one real message, then raises KafkaException on every
    commit -- the real failure mode a broker hiccup or an in-flight
    rebalance can cause, which the previous asynchronous=True default
    silently swallowed instead of surfacing.
    """

    def __init__(self, messages):
        self._messages = list(messages)
        self.commit_attempts = 0

    def subscribe(self, topics):
        pass

    def poll(self, timeout):
        return self._messages.pop(0) if self._messages else None

    def commit(self, msg, asynchronous=False):
        self.commit_attempts += 1
        raise KafkaException(KafkaError(KafkaError._TIMED_OUT))

    def close(self):
        pass


def test_run_consumer_counts_commit_failures_without_crashing_the_loop():
    """Regression test for a real bug: run_consumer used to call
    consumer.commit(msg) with the library's asynchronous=True default
    and no error handling at all, so a real commit failure was silently
    invisible -- contradicting the function's own documented redelivery
    guarantee. This fails on the pre-fix code (KafkaException propagates
    up uncaught, run_consumer never returns) and passes once the commit
    is synchronous and its failure is counted, not swallowed or raised.
    """
    event = make_event(EventType.CLICK, "U1", "N1", 1, "t")
    fake_consumer = _FailingCommitConsumer([_FakeMessage(event.to_json().encode())])

    with patch("recommender.streaming.consumer.build_consumer", return_value=fake_consumer):
        result = run_consumer(StreamConsumer(), group_id="g", max_messages=1, idle_timeout=0.1)

    assert result["messages_processed"] == 1
    assert result["commit_failures"] == 1
    assert fake_consumer.commit_attempts == 1
