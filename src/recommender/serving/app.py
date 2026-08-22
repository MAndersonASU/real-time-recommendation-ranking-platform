import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from recommender.serving.contract import RecommendationRequest, RecommendationResponse
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext, build_serving_context

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads the trained model, index, ranking pipeline, and durable
    cache exactly once at process start -- the same `ServingContext`
    every other real caller (tests, verify_*.py scripts) has already
    used since Phase 8, not a second, app-specific load path.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    _state["context"] = build_serving_context(redis_url=redis_url)
    yield
    _state.clear()


app = FastAPI(title="Recommendation Service", lifespan=lifespan)


def _context() -> ServingContext:
    return _state["context"]


@app.get("/health")
def health() -> dict:
    """Process liveness only -- is this process running at all. Whether
    its model/index/feature dependencies are actually ready to serve is
    a separate, later concern (docs/health-checks.md).
    """
    return {"status": "ok"}


@app.post("/recommend", response_model=RecommendationResponse)
def recommend_endpoint(request: RecommendationRequest) -> RecommendationResponse:
    return safe_recommend(request, _context())
