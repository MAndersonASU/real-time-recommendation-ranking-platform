import redis

from recommender.features.cold_start import (
    DEFAULT_DURABLE_FEATURES,
    DEFAULT_RECENT_FEATURES,
    get_online_features,
)
from recommender.features.online_features import DurableUserFeatures, RecentUserFeatures
from recommender.features.state_store import RedisCircuitBreaker, save_recent_features


class _FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)


class _DownRedis:
    """Mimics an unreachable Redis: every call raises, the same way the
    real client raises `redis.exceptions.ConnectionError`/`TimeoutError`
    (both `RedisError` subclasses) against a genuinely dead host.
    """

    def get(self, key):
        raise redis.exceptions.ConnectionError("real redis is not reachable")


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


def test_use_recent_features_false_ignores_a_real_redis_record():
    client = _FakeRedis()
    save_recent_features(
        client,
        RecentUserFeatures(
            user_id="u1", recent_clicked_items=["n5"], impressions_seen=3,
            clicks_seen=1, last_event_time="2019-11-15T09:00:00",
        ),
    )

    result = get_online_features(
        "u1", durable_features_by_user={}, redis_client=client, use_recent_features=False
    )

    assert result.recent == DEFAULT_RECENT_FEATURES
    assert result.recent_is_fallback is True


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


# --- REDIS-DEGRADED-PATH-61: a Redis failure degrades, it does not raise ---


def test_a_real_redis_error_degrades_to_the_neutral_default_instead_of_raising():
    """Regression test for a real bug, found by audit: a Redis failure
    used to propagate out of this function (uncaught `RedisError`),
    which the caller in `recommend()` turned into a `DependencyUnavailableError`
    and `safe_recommend` then answered with the full, unpersonalized
    popularity fallback -- discarding durable features that Redis being
    down has no bearing on. This function now catches the failure itself
    and reports it as an absent recent record, same shape as an ordinary
    cold user, plus the narrower `redis_unavailable` flag a caller that
    cares about the distinction can check.
    """
    durable = {"u1": DurableUserFeatures(user_id="u1", dominant_category="tech", lifetime_click_count=5)}

    result = get_online_features("u1", durable_features_by_user=durable, redis_client=_DownRedis())

    assert result.durable == durable["u1"]
    assert result.durable_is_fallback is False
    assert result.recent == DEFAULT_RECENT_FEATURES
    assert result.recent_is_fallback is True
    assert result.redis_unavailable is True


def test_use_recent_features_false_never_reports_redis_as_unavailable():
    # A deliberate per-call opt-out is not a failure -- Redis is never
    # even contacted, so there is nothing to report as down.
    result = get_online_features(
        "u1", durable_features_by_user={}, redis_client=_DownRedis(), use_recent_features=False
    )

    assert result.redis_unavailable is False


def test_circuit_breaker_records_success_and_failure_from_real_lookups():
    breaker = RedisCircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    client = _FakeRedis()

    get_online_features("u1", durable_features_by_user={}, redis_client=client, circuit_breaker=breaker)
    assert breaker.is_open is False

    get_online_features("u1", durable_features_by_user={}, redis_client=_DownRedis(), circuit_breaker=breaker)
    assert breaker.is_open is False  # one failure, threshold is 2
    get_online_features("u1", durable_features_by_user={}, redis_client=_DownRedis(), circuit_breaker=breaker)
    assert breaker.is_open is True  # second consecutive failure trips it


def test_an_open_circuit_breaker_skips_the_redis_call_entirely():
    """Once open, the point is that a request must not even attempt the
    connection -- `_DownRedis` would raise the same way regardless, but
    an open breaker must report the request as skipped without calling
    it, which the real code path can't do fast if it dials in anyway.
    """
    breaker = RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=60.0)
    breaker.record_failure()
    assert breaker.is_open is True

    calls = []

    class _CountingRedis:
        def get(self, key):
            calls.append(key)
            raise redis.exceptions.ConnectionError("should never be reached")

    result = get_online_features(
        "u1", durable_features_by_user={}, redis_client=_CountingRedis(), circuit_breaker=breaker
    )

    assert calls == []
    assert result.redis_unavailable is True
    assert result.recent == DEFAULT_RECENT_FEATURES
