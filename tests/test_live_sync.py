from recommender.features.fake_redis import InMemoryRedis
from recommender.features.live_sync import SyncingStreamConsumer
from recommender.features.state_store import load_recent_features
from recommender.streaming.consumer import StreamConsumer
from recommender.streaming.schema import EventType, make_event

# The project's single in-process Redis stand-in, rather than a second
# copy here: this one implements SET NX, which claim_event's idempotency
# guarantee depends on. Real latency and real expiry behavior are proven
# separately, against the actual running container, in
# verify_state_store.py and verify_live_sync.py.
_FakeRedis = InMemoryRedis


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


def test_syncing_consumer_restores_prior_state_after_a_restart():
    """Regression test for a real bug: a restarted consumer (a brand new
    SyncingStreamConsumer instance, same Redis) used to start every
    user's in-process state empty, so the first event after restart
    overwrote a real durable record with a blank one -- a real click
    history and click count silently vanishing. This fails on the
    pre-fix code (state.recent_clicked_items == [] and clicks_seen == 0
    after the second consumer's first event) and passes once
    _get_or_create_state restores from Redis instead of defaulting.
    """
    client = _FakeRedis()

    consumer_before_restart = SyncingStreamConsumer(client)
    consumer_before_restart.process(make_event(EventType.IMPRESSION, "u1", "n1", 1, "t1").to_json())
    consumer_before_restart.process(make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json())

    before = load_recent_features(client, "u1")
    assert before.recent_clicked_items == ["n1"]
    assert before.clicks_seen == 1
    assert before.impressions_seen == 1

    # A real restart: a brand new consumer instance, same Redis, no
    # in-process memory of "u1" at all.
    consumer_after_restart = SyncingStreamConsumer(client)
    consumer_after_restart.process(make_event(EventType.IMPRESSION, "u1", "n2", 2, "t2").to_json())

    after = load_recent_features(client, "u1")
    assert after.recent_clicked_items == ["n1"]  # prior click history preserved, not wiped
    assert after.clicks_seen == 1  # prior click count preserved
    assert after.impressions_seen == 2  # correctly incremented from the restored state
    assert after.last_event_time == "t2"


def test_syncing_consumer_does_not_double_count_after_a_crash_before_commit():
    """Regression test for real at-least-once duplication: the Redis
    mutation and the Kafka offset commit are separate operations, so a
    crash between them redelivers the message after restart -- and the
    in-process dedup set does not survive a restart either, since a new
    process starts it empty. This once counted the same real click
    twice.

    `claim_event` closes it by storing the resulting state inside a
    single atomic `SET NX` claim, so the redelivery recovers the state
    that event already produced instead of applying it again. Fails on
    the pre-fix code (clicks_seen == 2) and passes now.
    """
    client = _FakeRedis()
    click_event = make_event(EventType.CLICK, "u1", "n1", 1, "t1")
    raw = click_event.to_json()

    # The real click is processed and its effect written to Redis --
    # then, in this scenario, the process crashes before the Kafka
    # offset commit that would have followed.
    consumer_before_crash = SyncingStreamConsumer(client)
    assert consumer_before_crash.process(raw) is True
    assert load_recent_features(client, "u1").clicks_seen == 1

    # A real restart: a brand new consumer instance (empty
    # _seen_event_ids), same Redis. Because the offset was never
    # committed, the same message is redelivered and reprocessed.
    consumer_after_restart = SyncingStreamConsumer(client)
    assert consumer_after_restart.process(raw) is False

    after_redelivery = load_recent_features(client, "u1")
    assert after_redelivery.clicks_seen == 1
    assert consumer_after_restart.counters.duplicates_skipped == 1


def test_syncing_consumer_restores_correct_state_for_the_user_after_a_redelivery():
    """A redelivery must leave the consumer's own in-process state
    correct too, not just the Redis record -- otherwise the next real
    event for that user would be applied on top of a state that had
    already counted the redelivered event locally.
    """
    client = _FakeRedis()
    first = make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json()

    SyncingStreamConsumer(client).process(first)
    restarted = SyncingStreamConsumer(client)
    restarted.process(first)  # redelivered, must be repaired not re-applied

    # A genuinely new event now applies on top of the correct state.
    restarted.process(make_event(EventType.CLICK, "u1", "n2", 1, "t2").to_json())

    final = load_recent_features(client, "u1")
    assert final.clicks_seen == 2
    assert final.recent_clicked_items == ["n1", "n2"]


def test_get_or_create_state_only_hits_redis_once_per_user():
    """The restore-from-Redis path should only run on a user's first
    touch per process, not on every event -- otherwise every single
    event would pay a real Redis round-trip instead of just the first.
    """
    client = _FakeRedis()
    load_count = {"n": 0}
    real_get = client.get

    def counting_get(key):
        load_count["n"] += 1
        return real_get(key)

    client.get = counting_get
    consumer = SyncingStreamConsumer(client)

    consumer.process(make_event(EventType.IMPRESSION, "u1", "n1", 1, "t1").to_json())
    consumer.process(make_event(EventType.CLICK, "u1", "n2", 2, "t2").to_json())
    consumer.process(make_event(EventType.IMPRESSION, "u1", "n3", 3, "t3").to_json())

    assert load_count["n"] == 1
