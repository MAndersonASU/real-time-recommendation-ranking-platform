import logging
from unittest.mock import patch

import redis
from fastapi.testclient import TestClient
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.monitoring.quality_signals import QualitySignalTracker
from recommender.monitoring.structured_logging import hash_user_id
from recommender.serving import app as app_module
from recommender.serving import demo as demo_module
from tests.test_pipeline import NEWS, _build_context

NEWS_BY_ID = NEWS.set_index("news_id")


def _dead_redis_client() -> redis.Redis:
    return redis.Redis(
        host="localhost", port=6390, socket_connect_timeout=0.2, socket_timeout=0.2,
        decode_responses=True, retry=Retry(NoBackoff(), 0), retry_on_error=[],
    )


def _client() -> TestClient:
    # Injects a synthetic ServingContext directly, bypassing the real
    # lifespan startup (which loads real trained artifacts from disk) --
    # the same synthetic fixture every other pipeline test already uses.
    context = _build_context()
    app_module._state["context"] = context
    app_module._state["quality_tracker"] = QualitySignalTracker(catalog_size=len(context.news_ids))
    return TestClient(app_module.app)


def test_health_endpoint_reports_ok():
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommend_endpoint_returns_a_valid_response():
    response = _client().post(
        "/recommend", json={"user_id": "u1", "num_candidates": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "u1"
    assert len(body["recommendations"]) == 3


def test_metrics_endpoint_reflects_a_real_request():
    client = _client()
    client.post("/recommend", json={"user_id": "u1", "num_candidates": 2})

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "recommend_requests_total" in response.text
    assert "recommend_candidate_count" in response.text


def test_recommend_endpoint_rejects_an_invalid_request():
    response = _client().post(
        "/recommend", json={"user_id": "u1", "num_candidates": 0}
    )

    assert response.status_code == 422


def test_ready_reports_ready_and_redis_ok_when_everything_works():
    response = _client().get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["dependencies"]["model_index_ranking"] == "ok"
    assert body["dependencies"]["redis"] == "ok"


def test_ready_stays_ready_but_reports_redis_degraded_on_a_real_connection_failure():
    context = _build_context()
    context.redis_client = redis.Redis(
        host="localhost", port=6390, socket_connect_timeout=0.2, socket_timeout=0.2,
        decode_responses=True, retry=Retry(NoBackoff(), 0), retry_on_error=[],
    )
    app_module._state["context"] = context

    response = TestClient(app_module.app).get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert "degraded" in body["dependencies"]["redis"]


def test_ready_returns_503_when_the_serving_context_never_loaded():
    app_module._state.pop("context", None)

    response = TestClient(app_module.app).get("/ready")

    assert response.status_code == 503


def test_recommend_endpoint_still_returns_the_real_response_when_quality_tracking_crashes():
    """Regression test for a real bug: quality tracking and structured
    logging ran with no exception boundary at all, after record_response()
    had already counted the recommendation as a success -- so a crash in
    that block (a real one existed: a concurrency race in
    QualitySignalTracker) turned an already-successful, already-computed
    response into a client-facing 500. Fails on the pre-fix code (the
    request raises before returning) and passes once that block is
    wrapped so a failure there can't override a real, valid response.
    """
    client = _client()

    with patch.object(
        app_module.QualitySignalTracker, "record", side_effect=RuntimeError("simulated tracker crash")
    ):
        response = client.post("/recommend", json={"user_id": "u1", "num_candidates": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "u1"
    assert len(body["recommendations"]) == 3


def test_demo_endpoint_rejects_an_out_of_range_num_candidates_with_422_not_500():
    """Regression test for a real bug, found by audit: `num_candidates`
    had no query-level constraint, so an out-of-range value reached
    `RecommendationRequest` deep inside `build_demo_data` and raised a
    raw, uncaught pydantic ValidationError -- an unhandled 500. Fails on
    the pre-fix code (500) and passes once the query parameter itself
    enforces the same bounds `/recommend`'s body already does.
    """
    client = _client()

    response = client.get("/demo/u1", params={"num_candidates": 0})

    assert response.status_code == 422


def test_demo_endpoint_falls_back_instead_of_crashing_on_a_real_redis_failure():
    """Regression test for a real bug, found by audit: `/demo` called
    `recommend()` directly, bypassing the same `safe_recommend` fallback
    `/recommend` already uses -- so a real dependency failure (here, an
    unreachable Redis) crashed this page with an unhandled 500 instead of
    degrading to the popularity fallback. Fails on the pre-fix code (500)
    and passes once `/demo` goes through `safe_recommend` too.
    """
    context = _build_context(redis_client=_dead_redis_client())
    app_module._state["context"] = context
    demo_module._news_by_id.cache_clear()

    with patch.object(demo_module, "load_catalog", return_value=NEWS):
        response = TestClient(app_module.app).get("/demo/u1", params={"num_candidates": 3})

    assert response.status_code == 200
    assert "u1" in response.text


def test_demo_endpoint_logs_a_hashed_not_raw_user_id():
    """Regression test for a real bug, found by audit: the access-log
    middleware logs `request.url.path` verbatim for every route, so the
    raw user id was written to the log for every `/demo/{user_id}`
    request -- inconsistent with `/recommend`'s own log line, which only
    ever logs a hash. Fails on the pre-fix code (the raw id appears in
    the logged path) and passes once that path is redacted before
    logging.
    """
    client = _client()
    demo_module._news_by_id.cache_clear()
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    app_module.logger.addHandler(handler)
    try:
        with patch.object(demo_module, "load_catalog", return_value=NEWS):
            client.get("/demo/a-very-identifiable-raw-user-id", params={"num_candidates": 1})
    finally:
        app_module.logger.removeHandler(handler)

    logged_paths = [r.__dict__["path"] for r in records if "path" in r.__dict__]
    assert logged_paths, "expected the access-log middleware to log at least one request"
    assert all("a-very-identifiable-raw-user-id" not in path for path in logged_paths)
    assert any(hash_user_id("a-very-identifiable-raw-user-id") in path for path in logged_paths)


def test_loggable_path_redacts_a_demo_path_with_a_trailing_slash_too():
    """Regression test for a real gap found while verifying the fix
    above against the live container: a `/demo/{user_id}/` request
    (trailing slash -- what FastAPI's own redirect-to-canonical-path
    logic still logs once on its own, before the redirect) didn't match
    the first version of `_DEMO_PATH_PATTERN` at all, since it required
    the path to end immediately after the user id with no trailing
    character. Fails on that version (the raw id passes through
    untouched) and passes once the pattern also accepts an optional
    trailing slash.
    """
    redacted = app_module._loggable_path("/demo/a-very-identifiable-raw-user-id/")

    assert "a-very-identifiable-raw-user-id" not in redacted
    assert redacted == f"/demo/{hash_user_id('a-very-identifiable-raw-user-id')}/"


def test_recommend_endpoint_preserves_the_x_request_id_header_on_a_real_dependency_failure():
    """A real dependency failure (Redis unreachable) is a known,
    expected condition -- `safe_recommend` degrades it to a 200
    popularity-fallback response, not an error, so it takes the
    middleware's normal success path rather than the except branch
    covered by test_unhandled_exception_still_gets_an_x_request_id_
    header_and_an_error_log above. Confirms that path also carries a
    real X-Request-ID, not just the true-500 path.
    """
    context = _build_context(redis_client=_dead_redis_client())
    app_module._state["context"] = context
    app_module._state["quality_tracker"] = QualitySignalTracker(catalog_size=len(context.news_ids))
    client = TestClient(app_module.app)

    response = client.post("/recommend", json={"user_id": "u1", "num_candidates": 3})

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers


def test_unhandled_exception_still_gets_an_x_request_id_header_and_an_error_log():
    """Regression test for a real bug, found by a follow-up audit: an
    unhandled exception raised inside a route bypasses this middleware's
    own return path entirely (call_next itself raises), so neither the
    X-Request-ID header nor any access-log line was ever written for
    that request. Fails on the pre-fix code (no header, no log line, a
    raw framework 500 with no diagnosable trace) and passes once the
    middleware wraps call_next in its own try/except.
    """
    _client()  # sets up _state["context"] / _state["quality_tracker"]
    client = TestClient(app_module.app, raise_server_exceptions=False)
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    app_module.logger.addHandler(handler)
    try:
        # Quality tracking already runs inside its own try/except in the
        # route (a separate, earlier fix), so patching that would not
        # reproduce a truly unhandled exception -- patch safe_recommend
        # itself instead, the one call the route never wraps.
        with patch.object(app_module, "safe_recommend", side_effect=RuntimeError("simulated unhandled bug")):
            response = client.post("/recommend", json={"user_id": "u1", "num_candidates": 3})
    finally:
        app_module.logger.removeHandler(handler)

    assert response.status_code == 500
    assert "X-Request-ID" in response.headers
    assert response.json() == {"detail": "Internal server error"}

    failed_records = [r for r in records if r.__dict__.get("event") == "request_failed"]
    assert len(failed_records) == 1
    assert failed_records[0].__dict__["request_id"] == response.headers["X-Request-ID"]
    assert failed_records[0].__dict__["status_code"] == 500
