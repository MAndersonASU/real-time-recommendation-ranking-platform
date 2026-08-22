import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from recommender.monitoring.metrics import (
    record_error,
    record_feature_lookup_latency,
    record_response,
)
from recommender.serving.config import load_settings
from recommender.serving.contract import RecommendationRequest, RecommendationResponse
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext, build_serving_context

logger = logging.getLogger("recommender.serving.app")

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads the trained model, index, ranking pipeline, and durable
    cache exactly once at process start -- the same `ServingContext`
    every other real caller (tests, verify_*.py scripts) has already
    used since Phase 8, not a second, app-specific load path.

    A missing model/index/ranking-pipeline file is a real, validated
    startup dependency: there's no per-request fallback for "the whole
    context couldn't even be built" (unlike a single unreachable Redis
    call, which `safe_recommend` already handles gracefully), so this
    fails loudly and immediately with a diagnosable message instead of
    an unexplained crash the first time a request arrives.
    """
    settings = load_settings()
    try:
        _state["context"] = build_serving_context(redis_url=settings.redis_url_with_auth())
    except OSError as exc:
        logger.error(
            "Serving context failed to build -- a required model/index/ranking-pipeline "
            "file was not found. Confirm the data volume is mounted and the offline "
            "pipeline has produced its artifacts before starting this service. (%s)",
            exc,
        )
        raise
    yield
    _state.clear()


app = FastAPI(title="Recommendation Service", lifespan=lifespan)


def _context() -> ServingContext:
    return _state["context"]


@app.get("/health")
def health() -> dict:
    """Process liveness only -- is this process running at all, with no
    check of whether it can actually serve a request. A process stuck
    mid-startup, or one whose model failed to load, is still alive; a
    liveness probe should restart it only if the process itself has
    hung or crashed, not because a dependency is degraded (that's what
    /ready is for).
    """
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness, separated from liveness (docs/health-checks.md).
    "Ready" means the model, index, and ranking pipeline actually loaded
    -- the one dependency with no per-request fallback, so a caller
    hitting this service before it finishes loading needs a real 503,
    not a response built from a context that doesn't exist yet.

    Redis is checked too, but reported as a separate, non-fatal
    dependency status rather than failing readiness outright: an
    unreachable Redis degrades personalization (`safe_recommend` falls
    back to popularity ranking) without making the service unable to
    serve a valid response at all, so pulling it out of a load
    balancer's rotation over a degraded-but-working Redis would be the
    wrong call.
    """
    context = _state.get("context")
    if context is None:
        raise HTTPException(status_code=503, detail="serving context not loaded yet")

    try:
        context.redis_client.ping()
        redis_status = "ok"
    except Exception:  # noqa: BLE001 -- any real connection failure means "degraded", not a crash
        redis_status = "degraded (falls back to popularity ranking)"

    return {
        "ready": True,
        "dependencies": {"model_index_ranking": "ok", "redis": redis_status},
    }


@app.get("/metrics")
def metrics() -> Response:
    """Real operational metrics for this process, in Prometheus's own
    text format (docs/operational-metrics.md) -- request rate, errors,
    latency, candidate counts, fallback rate, and durable/recent cache
    hit rates, all recorded from the one place a response is actually
    produced below, never a second, separately-tracked copy.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/recommend", response_model=RecommendationResponse)
def recommend_endpoint(request: RecommendationRequest) -> RecommendationResponse:
    fell_back = {"value": False}

    def _mark_fallback() -> None:
        fell_back["value"] = True

    stage_timings: dict[str, float] = {}
    start = time.perf_counter()
    try:
        response = safe_recommend(
            request, _context(), on_fallback=_mark_fallback, stage_timings=stage_timings
        )
    except Exception:
        record_error()
        raise
    record_response(response, is_fallback=fell_back["value"], latency_seconds=time.perf_counter() - start)
    if "feature_lookup_ms" in stage_timings:
        record_feature_lookup_latency(stage_timings["feature_lookup_ms"] / 1000)
    return response
