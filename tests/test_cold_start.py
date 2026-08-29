import json

import pytest
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


def test_a_malformed_redis_record_still_lets_a_later_request_probe_again():
    """Regression test for a real bug, found by external review: a probe
    attempt that raises something other than `RedisError` -- here,
    malformed JSON actually stored under the key, which `load_recent_features`
    parses with a bare `json.loads` -- reached neither `record_success`
    nor `record_failure`, since the `except RedisError` clause doesn't
    match a `JSONDecodeError`. The breaker's one HALF_OPEN probe slot
    was claimed by `allow_request()` and never released, so it had no
    way to ever probe again: `RedisCircuitBreaker` has no timeout-based
    recovery from a stuck HALF_OPEN, only `record_success`/`record_failure`
    resolve it.

    Fails on the pre-fix code (a later `allow_request()` stays `False`
    forever after the malformed-JSON exception) and passes once every
    exit path -- including one that re-raises -- reports an outcome to
    the breaker first. The exception itself must still propagate: it is
    a real bug (corrupted state, not a Redis failure), not something
    this function is allowed to silently swallow.
    """
    breaker = RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
    breaker.record_failure()  # opens it; cooldown=0.0, so a probe is already eligible

    class _MalformedRedis:
        def get(self, key):
            return "not valid json {{{"

    with pytest.raises(json.JSONDecodeError):
        get_online_features("u1", durable_features_by_user={}, redis_client=_MalformedRedis(), circuit_breaker=breaker)

    # The probe slot must be released -- a later request can attempt a
    # real connection again, not be stuck reporting redis_unavailable
    # forever regardless of Redis's actual health. Calling
    # `get_online_features` directly (rather than checking
    # `breaker.allow_request()` first) matters here: `allow_request()`
    # itself claims the probe slot as a side effect, so a standalone
    # check beforehand would consume the very probe this assertion
    # means to observe.
    result = get_online_features("u1", durable_features_by_user={}, redis_client=_FakeRedis(), circuit_breaker=breaker)
    assert result.redis_unavailable is False
    assert breaker.is_open is False
