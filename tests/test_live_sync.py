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


def test_a_duplicate_returns_the_users_current_state():
    """A redelivery must report where the user actually is now, not the
    state that existed when the event was first applied -- restoring the
    latter is what rolled users backwards.
    """
    from recommender.features.state_store import claim_and_apply_event

    client = _FakeRedis()
    claim_and_apply_event(client, "evt-1", "u1", "click", "n1", "t1", 20)
    claim_and_apply_event(client, "evt-2", "u1", "click", "n2", "t2", 20)

    status, current = claim_and_apply_event(client, "evt-1", "u1", "click", "n1", "t1", 20)

    assert status == 0
    assert current.recent_clicked_items == ["n1", "n2"]
    assert current.clicks_seen == 2


def test_two_consumers_that_both_read_before_writing_lose_nothing():
    """The lost update the version check could not prevent: both
    consumers loaded empty state, so each derived a complete state from a
    stale basis and the second overwrote the first.

    Applying the event delta inside the atomic script removes the local
    basis entirely, so there is nothing to go stale.
    """
    client = _FakeRedis()
    first = SyncingStreamConsumer(client)
    second = SyncingStreamConsumer(client)

    # Both observe the user before either writes.
    first._get_or_create_state("u1")
    second._get_or_create_state("u1")

    first.process(make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json())
    second.process(make_event(EventType.CLICK, "u1", "n2", 2, "t2").to_json())

    final = load_recent_features(client, "u1")
    assert final.clicks_seen == 2
    assert set(final.recent_clicked_items) == {"n1", "n2"}


def test_an_impression_is_never_reapplied_as_a_click():
    """The retry path inferred event type from whether the attempted
    state carried clicked items, so an impression for a user who already
    had click history was re-applied as a click -- duplicating the item
    and inflating the click count.
    """
    client = _FakeRedis()
    SyncingStreamConsumer(client).process(
        make_event(EventType.CLICK, "u1", "n1", 1, "t1").to_json()
    )

    SyncingStreamConsumer(client).process(
        make_event(EventType.IMPRESSION, "u1", "n9", 2, "t2").to_json()
    )

    final = load_recent_features(client, "u1")
    assert final.recent_clicked_items == ["n1"]
    assert final.clicks_seen == 1
    assert final.impressions_seen == 1


def test_impression_and_click_conflicts_each_apply_exactly_once():
    """Every ordering of the two event types must land both effects."""
    for first_type, second_type in (
        (EventType.CLICK, EventType.CLICK),
        (EventType.CLICK, EventType.IMPRESSION),
        (EventType.IMPRESSION, EventType.CLICK),
        (EventType.IMPRESSION, EventType.IMPRESSION),
    ):
        client = _FakeRedis()
        a = SyncingStreamConsumer(client)
        b = SyncingStreamConsumer(client)
        a._get_or_create_state("u1")
        b._get_or_create_state("u1")

        a.process(make_event(first_type, "u1", "n1", 1, "t1").to_json())
        b.process(make_event(second_type, "u1", "n2", 2, "t2").to_json())

        final = load_recent_features(client, "u1")
        expected_clicks = sum(t is EventType.CLICK for t in (first_type, second_type))
        expected_impressions = 2 - expected_clicks
        assert final.clicks_seen == expected_clicks, (first_type, second_type)
        assert final.impressions_seen == expected_impressions, (first_type, second_type)

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
