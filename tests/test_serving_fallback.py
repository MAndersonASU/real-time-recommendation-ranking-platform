import logging

import pytest
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.monitoring.structured_logging import hash_user_id
from recommender.serving.contract import RecommendationRequest
from recommender.serving.errors import DependencyUnavailableError
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
    """A fallback must be visible, not silent: safe_recommend logs the
    real exception (with traceback) every time it falls back, so a spike
    in fallbacks is investigable from the logs.
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


def test_safe_recommend_never_logs_the_raw_user_id():
    """Regression test for a real privacy bug, found by a follow-up
    audit: the fallback-logging line introduced by an earlier fix logged
    `request.user_id` directly. Fails on that version (the raw,
    identifiable id appears in the log record) and passes once the
    logged value is hashed with the same helper `/recommend` and
    `/demo` already use.
    """
    raw_user_id = "a-very-identifiable-raw-user-id-12345"
    context = _build_context(redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id=raw_user_id, num_candidates=4)
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
    logged_message = records[0].getMessage()
    assert raw_user_id not in logged_message
    assert hash_user_id(raw_user_id) in logged_message


def test_safe_recommend_falls_back_with_the_real_reason():
    context = _build_context(redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id="u1", num_candidates=4)
    reasons = []

    safe_recommend(request, context, on_fallback=reasons.append)

    assert reasons == ["redis_unavailable"]


def test_safe_recommend_lets_a_genuine_programming_bug_propagate_not_fall_back():
    """Regression test distinguishing a real dependency failure from a
    real programming bug, per the follow-up audit's explicit ask: only
    DependencyUnavailableError (raised at the specific boundaries where
    a known dependency's own exception was caught and translated)
    triggers a fallback. A bug elsewhere in the pipeline -- here, a
    ValueError from the ranking model's own predict_proba, standing in
    for a real feature-construction defect -- must reach the caller
    as-is, not be silently reported as a successful popularity response.
    """
    from unittest.mock import patch

    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    with patch.object(
        context.ranking_model, "predict_proba", side_effect=ValueError("simulated programming bug")
    ), pytest.raises(ValueError, match="simulated programming bug"):
        safe_recommend(request, context)


def test_dependency_unavailable_error_is_not_confused_with_an_ordinary_runtime_error():
    """A plain RuntimeError raised somewhere safe_recommend does not
    explicitly translate must not be caught -- only the project's own
    DependencyUnavailableError type is.
    """
    from unittest.mock import patch

    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    with patch.object(
        context.ranking_model, "predict_proba", side_effect=RuntimeError("unrelated runtime error")
    ), pytest.raises(RuntimeError, match="unrelated runtime error"):
        safe_recommend(request, context)

    assert issubclass(DependencyUnavailableError, Exception)
    assert not issubclass(RuntimeError, DependencyUnavailableError)
