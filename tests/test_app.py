from unittest.mock import patch

import redis
from fastapi.testclient import TestClient
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.monitoring.quality_signals import QualitySignalTracker
from recommender.serving import app as app_module
from tests.test_pipeline import _build_context


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
