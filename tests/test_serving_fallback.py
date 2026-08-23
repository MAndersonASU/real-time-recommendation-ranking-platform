import logging

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import build_fallback_response, safe_recommend
from recommender.serving.pipeline import recommend
from tests.test_pipeline import _build_context


def _dead_redis_client() -> redis.Redis:
    # Nothing listens on this port -- a real, unmocked connection
    # failure, not a simulated one. redis-py retries a connection error
    # several times with backoff by default, which turned this into an
    # 8-second test even with a short timeout -- retry is disabled
    # explicitly so the real failure surfaces fast.
    return redis.Redis(
        host="localhost", port=6390, socket_connect_timeout=0.2, socket_timeout=0.2,
        decode_responses=True, retry=Retry(NoBackoff(), 0), retry_on_error=[],
    )


def test_safe_recommend_matches_the_real_path_when_everything_works():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    via_safe_recommend = safe_recommend(request, context)
    via_recommend = recommend(request, context)

    # generated_at is real wall-clock time, taken at two genuinely
    # different instants across these two calls -- excluded from the
    # comparison on purpose, not because equality doesn't matter here.
    assert via_safe_recommend.model_dump(exclude={"generated_at"}) == via_recommend.model_dump(
        exclude={"generated_at"}
    )


def test_safe_recommend_falls_back_on_a_real_redis_connection_failure():
    context = _build_context(redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    response = safe_recommend(request, context)

    assert len(response.recommendations) == 4
    assert response.durable_features_used is False
    assert response.recent_features_used is False


def test_fallback_response_orders_by_descending_popularity():
    context = _build_context()
    # n1 is the only item with a real click in TRAIN_BEHAVIORS's exploded
    # impressions ("n3-0 n1-1"), so it must lead every fallback slate.
    request = RecommendationRequest(user_id="anyone", num_candidates=3)

    response = build_fallback_response(request, context)

    assert response.recommendations[0].news_id == "n1"
    assert [item.rank for item in response.recommendations] == [1, 2, 3]


def test_fallback_response_scores_are_bounded_and_never_claims_personalization():
    context = _build_context()
    request = RecommendationRequest(user_id="anyone", num_candidates=5)

    response = build_fallback_response(request, context)

    assert all(0.0 <= item.score <= 1.0 for item in response.recommendations)
    assert response.durable_features_used is False
    assert response.recent_features_used is False


def test_safe_recommend_logs_the_real_exception_before_falling_back():
    """Regression test for a real, disclosed limitation, found by audit:
    DEPENDENCY_FAILURE_EXCEPTIONS includes RuntimeError, the common base
    torch and Faiss both raise for an unusable model/index -- broad
    enough that a genuine programming bug raising RuntimeError would
    also be silently swallowed into a "safe" fallback with no trace at
    all. Narrowing the catch would risk a real dependency outage no
    longer degrading gracefully, so the fix instead logs the real
    exception every time a fallback fires. Fails on the pre-fix code (no
    log record at all) and passes once the except block logs it.
    """
    context = _build_context(redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id="u1", num_candidates=4)
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("recommender.serving.fallback")
    handler = _Capture()
    logger.addHandler(handler)
    try:
        safe_recommend(request, context)
    finally:
        logger.removeHandler(handler)

    assert len(records) == 1
    assert records[0].exc_info is not None
