import logging
import time
from unittest.mock import patch

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


def _broken_two_tower_patch(context):
    """A real dependency failure that still triggers the full popularity
    fallback -- unlike a Redis failure (see the degrade tests below),
    the two-tower model is genuinely required for retrieval, so
    `recommend()` still translates this into `DependencyUnavailableError`.
    """
    return patch.object(
        context.two_tower_model, "user_vector", side_effect=RuntimeError("simulated model failure")
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


def test_safe_recommend_degrades_gracefully_on_a_real_redis_connection_failure():
    """REDIS-DEGRADED-PATH-61: a Redis failure must not throw away
    durable features and the trained model just because the live
    feature store is unreachable. Fails on the pre-fix code (this used
    to be indistinguishable from the two-tower/Faiss case below -- both
    fell all the way back to flat popularity) and passes once a Redis
    failure degrades to exactly the same response a deliberate
    `use_recent_features=False` ablation run already produces: real
    retrieval and ranking, on durable features, with an empty recent-
    features input.

    Both calls share one `_build_context()` (only `redis_client` swapped
    via `dataclasses.replace`), not two independent ones: since
    SERVING-DURABLE-HISTORY-69, an empty recent history falls back to
    the user's real durable history for retrieval, which now actually
    exercises the two-tower model -- `_build_context()` builds a fresh,
    randomly-initialized (untrained) model on every call, so two
    separate calls would legitimately produce two different embeddings
    for the same durable history, an unrelated fixture difference this
    test must not confuse with the real thing it checks.
    """
    from dataclasses import replace

    healthy_context = _build_context()
    context = replace(healthy_context, redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    degraded = safe_recommend(request, context)
    without_recent_features = recommend(request, healthy_context, use_recent_features=False)

    assert len(degraded.recommendations) == 4
    assert degraded.recent_features_used is False
    assert degraded.retrieval_history_source == "durable"
    assert degraded.model_dump(exclude={"generated_at"}) == without_recent_features.model_dump(
        exclude={"generated_at"}
    )


def test_safe_recommend_stays_fast_when_redis_is_down():
    """The point of the short timeout and explicit no-retry policy
    (`recommender.features.state_store.build_client`): a Redis failure
    must not turn one request into a multi-second stall. Before that
    fix, redis-py's own implicit retry-with-backoff silently doubled a
    failed connection attempt's cost; 2 seconds here is generous
    headroom above the configured 0.2s timeout for CI jitter, nowhere
    near the several seconds the old implicit retry produced.
    """
    context = _build_context(redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    start = time.perf_counter()
    safe_recommend(request, context)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0


def test_safe_recommend_reports_redis_degraded_without_triggering_a_fallback():
    context = _build_context(redis_client=_dead_redis_client())
    request = RecommendationRequest(user_id="u1", num_candidates=4)
    fallback_reasons = []
    degraded_calls = []

    safe_recommend(
        request,
        context,
        on_fallback=fallback_reasons.append,
        on_redis_degraded=lambda: degraded_calls.append(True),
    )

    assert fallback_reasons == []
    assert degraded_calls == [True]


def test_repeated_redis_failures_open_the_shared_circuit_breaker_and_skip_the_connection():
    """Requests don't all wait for the same timeout: once the breaker on
    `context` has seen enough consecutive failures, a later request must
    not even attempt to connect -- proven by timing, since a skipped
    attempt is far faster than the 0.2s connect timeout a real attempt
    against this dead client would pay.
    """
    context = _build_context(redis_client=_dead_redis_client())
    context.redis_circuit_breaker._failure_threshold = 2  # keep the test fast
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    for _ in range(2):
        safe_recommend(request, context)
    assert context.redis_circuit_breaker.is_open is True

    start = time.perf_counter()
    safe_recommend(request, context)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.15


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
    in fallbacks is investigable from the logs. Exercised with a broken
    two-tower model, not Redis -- a Redis failure no longer falls back
    at all (see the degrade tests above), so it can't exercise this path
    any more.
    """
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=4)
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("recommender.serving.fallback")
    handler = _Capture()
    logger.addHandler(handler)
    try:
        with _broken_two_tower_patch(context):
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
    context = _build_context()
    request = RecommendationRequest(user_id=raw_user_id, num_candidates=4)
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("recommender.serving.fallback")
    handler = _Capture()
    logger.addHandler(handler)
    try:
        with _broken_two_tower_patch(context):
            safe_recommend(request, context)
    finally:
        logger.removeHandler(handler)

    assert len(records) == 1
    logged_message = records[0].getMessage()
    assert raw_user_id not in logged_message
    assert hash_user_id(raw_user_id) in logged_message


def test_safe_recommend_falls_back_with_the_real_reason():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=4)
    reasons = []

    with _broken_two_tower_patch(context):
        safe_recommend(request, context, on_fallback=reasons.append)

    assert reasons == ["two_tower_inference_failed"]


def test_safe_recommend_lets_a_genuine_programming_bug_propagate_not_fall_back():
    """Regression test distinguishing a real dependency failure from a
    real programming bug: only DependencyUnavailableError (raised at
    the specific boundaries where
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
