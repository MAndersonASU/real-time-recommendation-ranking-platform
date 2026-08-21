from recommender.features.cold_start import (
    DEFAULT_DURABLE_FEATURES,
    DEFAULT_RECENT_FEATURES,
    get_online_features,
)
from recommender.features.online_features import DurableUserFeatures, RecentUserFeatures
from recommender.features.state_store import save_recent_features


class _FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)


def test_fully_unknown_user_falls_back_on_both_sides():
    result = get_online_features("ghost", durable_features_by_user={}, redis_client=_FakeRedis())

    assert result.durable == DEFAULT_DURABLE_FEATURES
    assert result.recent == DEFAULT_RECENT_FEATURES
    assert result.durable_is_fallback is True
    assert result.recent_is_fallback is True


def test_known_durable_user_with_no_live_events_yet():
    durable = {"u1": DurableUserFeatures(user_id="u1", dominant_category="tech", lifetime_click_count=42)}

    result = get_online_features("u1", durable_features_by_user=durable, redis_client=_FakeRedis())

    assert result.durable == durable["u1"]
    assert result.durable_is_fallback is False
    assert result.recent == DEFAULT_RECENT_FEATURES
    assert result.recent_is_fallback is True


def test_brand_new_user_who_is_already_actively_clicking():
    client = _FakeRedis()
    save_recent_features(
        client,
        RecentUserFeatures(
            user_id="new_user", recent_clicked_items=["n1"], impressions_seen=2,
            clicks_seen=1, last_event_time="2019-11-15T08:00:00",
        ),
    )

    result = get_online_features("new_user", durable_features_by_user={}, redis_client=client)

    assert result.durable == DEFAULT_DURABLE_FEATURES
    assert result.durable_is_fallback is True
    assert result.recent.recent_clicked_items == ["n1"]
    assert result.recent_is_fallback is False


def test_fully_known_user_needs_no_fallback_at_all():
    durable = {"u1": DurableUserFeatures(user_id="u1", dominant_category="sports", lifetime_click_count=10)}
    client = _FakeRedis()
    save_recent_features(
        client,
        RecentUserFeatures(
            user_id="u1", recent_clicked_items=["n5"], impressions_seen=3,
            clicks_seen=1, last_event_time="2019-11-15T09:00:00",
        ),
    )

    result = get_online_features("u1", durable_features_by_user=durable, redis_client=client)

    assert result.durable_is_fallback is False
    assert result.recent_is_fallback is False
    assert result.durable.dominant_category == "sports"
    assert result.recent.recent_clicked_items == ["n5"]
