from recommender.features.online_features import RecentUserFeatures, recent_features_from_user_state
from recommender.features.parity import compute_recent_features_offline
from recommender.streaming.consumer import MAX_RECENT_ITEMS, StreamConsumer
from recommender.streaming.schema import EventType, make_event


def _events():
    return [
        make_event(EventType.IMPRESSION, "u1", "n1", 1, "2019-11-15T08:00:00"),
        make_event(EventType.CLICK, "u1", "n1", 1, "2019-11-15T08:00:05"),
        make_event(EventType.IMPRESSION, "u1", "n2", 2, "2019-11-15T08:05:00"),
        make_event(EventType.CLICK, "u1", "n2", 2, "2019-11-15T08:05:03"),
        make_event(EventType.IMPRESSION, "u1", "n3", 3, "2019-11-15T09:00:00"),
        make_event(EventType.SKIP, "u1", "n3", 3, "2019-11-15T09:00:02"),
        # a second user, interleaved in time, to prove per-user isolation
        make_event(EventType.CLICK, "u2", "n9", 9, "2019-11-15T08:02:00"),
    ]


def _online_recent_features(events, user_id, cutoff):
    consumer = StreamConsumer()
    relevant = sorted((e for e in events if e.timestamp <= cutoff), key=lambda e: e.timestamp)
    for event in relevant:
        consumer.process(event.to_json())
    return recent_features_from_user_state(user_id, consumer.user_states[user_id])


def test_online_and_offline_recent_features_agree_at_several_cutoffs():
    events = _events()

    for cutoff in ["2019-11-15T08:00:05", "2019-11-15T08:05:03", "2019-11-15T09:00:02"]:
        offline = compute_recent_features_offline(events, "u1", cutoff)
        online = _online_recent_features(events, "u1", cutoff)
        assert online == offline


def test_parity_check_isolates_state_per_user():
    events = _events()
    cutoff = "2019-11-15T08:05:03"

    offline_u1 = compute_recent_features_offline(events, "u1", cutoff)
    offline_u2 = compute_recent_features_offline(events, "u2", cutoff)

    assert offline_u1.clicks_seen == 2
    assert offline_u2.clicks_seen == 1
    assert offline_u1.recent_clicked_items != offline_u2.recent_clicked_items


def test_offline_recompute_matches_online_bounded_history_truncation():
    events = [
        make_event(EventType.CLICK, "u1", f"n{i}", i, f"2019-11-15T08:{i:02d}:00")
        for i in range(MAX_RECENT_ITEMS + 5)
    ]
    cutoff = events[-1].timestamp

    offline = compute_recent_features_offline(events, "u1", cutoff)
    online = _online_recent_features(events, "u1", cutoff)

    assert len(offline.recent_clicked_items) == MAX_RECENT_ITEMS
    assert offline.recent_clicked_items == online.recent_clicked_items


def test_offline_recompute_has_no_signal_before_a_users_first_event():
    events = _events()

    before_anything = compute_recent_features_offline(events, "u1", "2019-11-15T07:59:59")

    assert before_anything == RecentUserFeatures(
        user_id="u1",
        recent_clicked_items=[],
        impressions_seen=0,
        clicks_seen=0,
        last_event_time=None,
    )
