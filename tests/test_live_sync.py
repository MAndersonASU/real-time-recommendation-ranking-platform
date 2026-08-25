from recommender.features.fake_redis import InMemoryRedis
from recommender.features.live_sync import SyncingStreamConsumer
from recommender.features.state_store import load_recent_features
from recommender.streaming.consumer import StreamConsumer
from recommender.streaming.schema import EventType, make_event

# The project's single in-process Redis stand-in, rather than a second
# copy here: this one implements SET NX and the atomic claim-and-apply
# script's contract, which the idempotency guarantee depends on. Real latency and real expiry behavior are proven
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

    `claim_and_apply_event` closes it: the claim and the state write
    happen in one atomic step, and a redelivery is refused rather than
    re-applied. Fails on the pre-fix code (clicks_seen == 2).
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


def test_prior_state_is_restored_from_redis_only_once_per_user():
    """The restore-from-Redis path must run only on a user's first touch
    per process, not on every event -- otherwise every event would pay a
    full state round-trip just to rebuild what the process already holds.

    This deliberately does not assert a total `get` count. Applying an
    event now also reads the user's current state version, because the
    atomic claim-and-apply is a compare-and-set and cannot check a
    version it has not read. That per-event read is the cost of not
    silently overwriting a concurrent writer; the restore itself still
    happens once.
    """
    client = _FakeRedis()
    consumer = SyncingStreamConsumer(client)
    restores = {"n": 0}
    real_restore = consumer._get_or_create_state

    def counting_restore(user_id):
        if user_id not in consumer.user_states:
            restores["n"] += 1
        return real_restore(user_id)

    consumer._get_or_create_state = counting_restore

    consumer.process(make_event(EventType.IMPRESSION, "u1", "n1", 1, "t1").to_json())
    consumer.process(make_event(EventType.CLICK, "u1", "n2", 2, "t2").to_json())
    consumer.process(make_event(EventType.IMPRESSION, "u1", "n3", 3, "t3").to_json())

    assert restores["n"] == 1
    assert "u1" in consumer.user_states


def test_a_late_duplicate_does_not_roll_state_back():
    """Regression test for real data loss: an earlier fix stored each
    event's resulting state inside its claim and restored that snapshot
    on redelivery. A duplicate of A arriving after B therefore rolled the
    user back to A's state and discarded B entirely -- strictly worse
    than the double-count it was preventing, because it loses real data
    rather than inflating a count.
    """
    client = _FakeRedis()
    event_a = make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json()
    event_b = make_event(EventType.CLICK, "u1", "n2", 2, "t2").to_json()

    consumer = SyncingStreamConsumer(client)
    consumer.process(event_a)
    consumer.process(event_b)
    assert load_recent_features(client, "u1").recent_clicked_items == ["n1", "n2"]

    # A restarted consumer receives A again, long after B was applied.
    restarted = SyncingStreamConsumer(client)
    assert restarted.process(event_a) is False

    after = load_recent_features(client, "u1")
    assert after.recent_clicked_items == ["n1", "n2"], "B was lost to a rollback"
    assert after.clicks_seen == 2
    # The consumer's own view must match the store, or the next real
    # event would be applied on top of rolled-back state.
    assert list(restarted.user_states["u1"].recent_clicked_items) == ["n1", "n2"]


def test_a_duplicate_returns_current_state_not_the_events_own_snapshot():
    from recommender.features.online_features import RecentUserFeatures
    from recommender.features.state_store import claim_and_apply_event, current_state_version

    client = _FakeRedis()
    first = RecentUserFeatures(
        user_id="u1", recent_clicked_items=["n1"], impressions_seen=1,
        clicks_seen=1, last_event_time="t1",
    )
    status, _ = claim_and_apply_event(client, "evt-1", first, current_state_version(client, "u1"))
    assert status == 1

    advanced = RecentUserFeatures(
        user_id="u1", recent_clicked_items=["n1", "n2"], impressions_seen=2,
        clicks_seen=2, last_event_time="t2",
    )
    status, _ = claim_and_apply_event(client, "evt-2", advanced, current_state_version(client, "u1"))
    assert status == 1

    # Replaying evt-1 must report the *current* state, not its own.
    status, returned = claim_and_apply_event(
        client, "evt-1", first, current_state_version(client, "u1")
    )
    assert status == 0
    assert returned.recent_clicked_items == ["n1", "n2"]


def test_a_stale_version_write_is_rejected_rather_than_overwriting():
    """Two consumers reading the same state concurrently must not
    silently overwrite one another.
    """
    from recommender.features.online_features import RecentUserFeatures
    from recommender.features.state_store import claim_and_apply_event, current_state_version

    client = _FakeRedis()
    base_version = current_state_version(client, "u1")

    winner = RecentUserFeatures(
        user_id="u1", recent_clicked_items=["n1"], impressions_seen=1,
        clicks_seen=1, last_event_time="t1",
    )
    assert claim_and_apply_event(client, "evt-a", winner, base_version)[0] == 1

    # A second consumer still holding the pre-write version.
    loser = RecentUserFeatures(
        user_id="u1", recent_clicked_items=["n9"], impressions_seen=1,
        clicks_seen=1, last_event_time="t9",
    )
    status, current = claim_and_apply_event(client, "evt-b", loser, base_version)

    assert status == 2, "a stale-version write must be refused"
    assert current.recent_clicked_items == ["n1"], "the winner's state must survive"


def test_concurrent_consumers_both_land_their_events():
    """The retry path must converge: two consumers processing different
    events for one user end with both events applied.
    """
    client = _FakeRedis()
    first = SyncingStreamConsumer(client)
    second = SyncingStreamConsumer(client)

    first.process(make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json())
    second.process(make_event(EventType.CLICK, "u1", "n2", 2, "t2").to_json())

    final = load_recent_features(client, "u1")
    assert final.clicks_seen == 2
    assert set(final.recent_clicked_items) == {"n1", "n2"}


def test_an_expired_claim_lets_an_event_apply_again():
    """The idempotency guarantee is bounded by claim retention. When a
    claim expires, a redelivery is treated as new -- documented rather
    than presented as unlimited protection.
    """
    from recommender.features.state_store import PROCESSED_KEY_PREFIX

    client = _FakeRedis()
    event = make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json()

    consumer = SyncingStreamConsumer(client)
    consumer.process(event)
    assert load_recent_features(client, "u1").clicks_seen == 1

    # Simulate the claim's TTL elapsing.
    for key in [k for k in client._data if k.startswith(PROCESSED_KEY_PREFIX)]:
        del client._data[key]

    SyncingStreamConsumer(client).process(event)
    assert load_recent_features(client, "u1").clicks_seen == 2, (
        "past the retention window a redelivery is applied again, by design"
    )
