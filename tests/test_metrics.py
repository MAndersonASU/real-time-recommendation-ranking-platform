from recommender.monitoring.metrics import (
    CANDIDATE_COUNT,
    DURABLE_CACHE_COUNT,
    EMPTY_RESPONSE_COUNT,
    FALLBACK_COUNT,
    RECENT_CACHE_COUNT,
    REQUEST_COUNT,
    record_error,
    record_response,
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
