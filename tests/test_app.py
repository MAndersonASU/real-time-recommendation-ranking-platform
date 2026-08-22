import redis
from fastapi.testclient import TestClient
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.serving import app as app_module
from tests.test_pipeline import _build_context


def _client() -> TestClient:
    # Injects a synthetic ServingContext directly, bypassing the real
    # lifespan startup (which loads real trained artifacts from disk) --
    # the same synthetic fixture every other pipeline test already uses.
    app_module._state["context"] = _build_context()
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
