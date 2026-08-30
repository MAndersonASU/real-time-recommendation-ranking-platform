import math

from recommender.monitoring.metrics import (
    CANDIDATE_COUNT,
    DURABLE_CACHE_COUNT,
    DURABLE_FEATURE_DATA_AGE,
    DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE,
    EMPTY_RESPONSE_COUNT,
    FALLBACK_COUNT,
    HTTP_REQUESTS_TOTAL,
    RECENT_CACHE_COUNT,
    REQUEST_COUNT,
    record_error,
    record_http_request,
    record_response,
    set_durable_feature_data_age,
)
from recommender.serving.contract import RecommendationResponse, RecommendedItem


def _count(counter, **labels) -> float:
    # prometheus_client has no public "read current value" API for a
    # single sample -- ._value.get() is the documented-by-convention way
    # test suites for this library read a counter back, used here only
    # to assert a *delta*, since these are real, shared, process-global
    # counters that other tests may also increment.
    target = counter.labels(**labels) if labels else counter
    return target._value.get()


def _response(recommendations=None, durable=True, recent=False) -> RecommendationResponse:
    from datetime import datetime

    return RecommendationResponse(
        user_id="u1",
        recommendations=recommendations or [],
        durable_features_used=durable,
        recent_features_used=recent,
        retrieval_history_source="recent" if recent else "durable" if durable else "global_popularity",
        generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001
    )


def test_record_response_increments_request_count_and_latency():
    before = _count(REQUEST_COUNT, outcome="success")

    record_response(_response(), is_fallback=False, latency_seconds=0.01)

    assert _count(REQUEST_COUNT, outcome="success") == before + 1


def test_record_response_flags_an_empty_response():
    before = _count(EMPTY_RESPONSE_COUNT)

    record_response(_response(recommendations=[]), is_fallback=False, latency_seconds=0.01)

    assert _count(EMPTY_RESPONSE_COUNT) == before + 1


def test_record_response_counts_a_real_fallback():
    before = _count(FALLBACK_COUNT, reason="unknown")

    record_response(_response(), is_fallback=True, latency_seconds=0.01)

    assert _count(FALLBACK_COUNT, reason="unknown") == before + 1


def test_record_response_labels_the_fallback_with_its_real_reason():
    before = _count(FALLBACK_COUNT, reason="redis_unavailable")

    record_response(_response(), is_fallback=True, fallback_reason="redis_unavailable", latency_seconds=0.01)

    assert _count(FALLBACK_COUNT, reason="redis_unavailable") == before + 1


def test_record_response_tracks_durable_and_recent_cache_hit_vs_miss():
    hit_before = _count(DURABLE_CACHE_COUNT, result="hit")
    miss_before = _count(RECENT_CACHE_COUNT, result="miss")

    record_response(_response(durable=True, recent=False), is_fallback=False, latency_seconds=0.01)

    assert _count(DURABLE_CACHE_COUNT, result="hit") == hit_before + 1
    assert _count(RECENT_CACHE_COUNT, result="miss") == miss_before + 1


def test_record_error_increments_the_error_outcome():
    before = _count(REQUEST_COUNT, outcome="error")

    record_error()

    assert _count(REQUEST_COUNT, outcome="error") == before + 1


def test_candidate_count_observes_the_real_response_size():
    sample_count_before = CANDIDATE_COUNT._sum.get()

    items = [RecommendedItem(news_id="n1", score=0.5, rank=1), RecommendedItem(news_id="n2", score=0.4, rank=2)]
    record_response(_response(recommendations=items), is_fallback=False, latency_seconds=0.01)

    assert CANDIDATE_COUNT._sum.get() == sample_count_before + 2


# --- HTTP-METRICS-SCOPE-66 --------------------------------------------


def test_record_http_request_labels_by_route_method_and_status_class():
    before = _count(HTTP_REQUESTS_TOTAL, route="/recommend", method="POST", status_class="4xx")

    record_http_request(route="/recommend", method="POST", status_code=422)

    assert _count(HTTP_REQUESTS_TOTAL, route="/recommend", method="POST", status_class="4xx") == before + 1


def test_record_http_request_groups_every_5xx_status_into_one_class():
    before_500 = _count(HTTP_REQUESTS_TOTAL, route="/recommend", method="POST", status_class="5xx")

    record_http_request(route="/recommend", method="POST", status_code=500)
    record_http_request(route="/recommend", method="POST", status_code=503)

    assert _count(HTTP_REQUESTS_TOTAL, route="/recommend", method="POST", status_class="5xx") == before_500 + 2


def test_record_http_request_does_not_touch_the_narrower_recommend_requests_total():
    # HTTP_REQUESTS_TOTAL and REQUEST_COUNT (recommend_requests_total)
    # are deliberately separate metrics at different scopes -- recording
    # one must never move the other.
    before = _count(REQUEST_COUNT, outcome="success") + _count(REQUEST_COUNT, outcome="error")

    record_http_request(route="/recommend", method="POST", status_code=422)

    after = _count(REQUEST_COUNT, outcome="success") + _count(REQUEST_COUNT, outcome="error")
    assert after == before


# --- UNKNOWN-DATA-AGE-67 ------------------------------------------------


def test_set_durable_feature_data_age_records_a_real_measurement():
    set_durable_feature_data_age(123.5)

    assert _count(DURABLE_FEATURE_DATA_AGE) == 123.5
    assert _count(DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE) == 1


def test_set_durable_feature_data_age_reports_unknown_as_nan_not_zero():
    """Regression test for a real bug, found by audit: the one call site
    that used to set this gauge directly did
    `DURABLE_FEATURE_DATA_AGE.set(snapshot["data_age_seconds"] or 0.0)`
    -- `None or 0.0` evaluates to `0.0` in Python, so "the newest-event
    time is unknown" and "the snapshot is 0 seconds old" were
    indistinguishable on the gauge, silently reporting unknown age as
    perfectly fresh. Fails on that pattern (a real 0.0, not NaN) and
    passes once `None` is handled explicitly.
    """
    set_durable_feature_data_age(None)

    assert math.isnan(_count(DURABLE_FEATURE_DATA_AGE))
    assert _count(DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE) == 0


def test_set_durable_feature_data_age_a_real_zero_is_still_distinguishable_from_unknown():
    # The other half of the same bug: a genuinely fresh snapshot (0.0
    # seconds old) must report as known, not get folded into "unknown"
    # by an overly broad fix either.
    set_durable_feature_data_age(0.0)

    assert _count(DURABLE_FEATURE_DATA_AGE) == 0.0
    assert _count(DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE) == 1
