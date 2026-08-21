from recommender.features.live_sync import SyncingStreamConsumer
from recommender.features.state_store import load_recent_features
from recommender.streaming.consumer import StreamConsumer
from recommender.streaming.schema import EventType, make_event


class _FakeRedis:
    """Satisfies the tiny subset of the redis.Redis interface state_store
    actually calls (set/get), so the wiring between SyncingStreamConsumer
    and state_store can be tested without a live Redis. Real latency and
    real expiry behavior are proven separately, against the actual
    running container, in verify_state_store.py and verify_live_sync.py.
    """

    def __init__(self):
        self._data: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)


def test_syncing_consumer_writes_recent_features_after_every_event():
    client = _FakeRedis()
    consumer = SyncingStreamConsumer(client)

    consumer.process(make_event(EventType.IMPRESSION, "u1", "n1", 1, "t1").to_json())
    consumer.process(make_event(EventType.CLICK, "u1", "n2", 1, "t2").to_json())

    features = load_recent_features(client, "u1")
    assert features.recent_clicked_items == ["n2"]
    assert features.impressions_seen == 1
    assert features.clicks_seen == 1
    assert features.last_event_time == "t2"


def test_syncing_consumer_leaves_untouched_users_out_of_the_store():
    client = _FakeRedis()
    consumer = SyncingStreamConsumer(client)

    consumer.process(make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json())

    assert load_recent_features(client, "u2") is None


def test_plain_stream_consumer_state_updated_hook_is_a_no_op():
    consumer = StreamConsumer()

    processed = consumer.process(make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json())

    assert processed is True
