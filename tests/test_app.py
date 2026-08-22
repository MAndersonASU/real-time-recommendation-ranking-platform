from fastapi.testclient import TestClient

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
