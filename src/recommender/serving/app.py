import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from recommender.monitoring.dashboard import render_dashboard_html
from recommender.monitoring.metrics import (
    MODEL_VERSION,
    record_error,
    record_feature_lookup_latency,
    record_response,
    update_quality_gauges,
)
from recommender.monitoring.quality_signals import QualitySignalTracker, compute_model_version
from recommender.monitoring.structured_logging import (
    configure_structured_logging,
    hash_user_id,
    new_request_id,
)
from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH
from recommender.serving.config import load_settings
from recommender.serving.contract import RecommendationRequest, RecommendationResponse
from recommender.serving.demo import DEFAULT_NUM_CANDIDATES, render_demo_html
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext, build_serving_context

configure_structured_logging()
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
        context = build_serving_context(redis_url=settings.redis_url_with_auth())
    except OSError as exc:
        logger.error(
            "Serving context failed to build -- a required model/index/ranking-pipeline "
            "file was not found. Confirm the data volume is mounted and the offline "
            "pipeline has produced its artifacts before starting this service. (%s)",
            exc,
        )
        raise
    _state["context"] = context
    _state["quality_tracker"] = QualitySignalTracker(catalog_size=len(context.news_ids))
    MODEL_VERSION.info({"sha256_prefix": compute_model_version(RETRIEVAL_MODEL_PATH)})
    yield
    _state.clear()


app = FastAPI(title="Recommendation Service", lifespan=lifespan)


@app.middleware("http")
async def request_id_and_access_log(request: Request, call_next):
    """Every request gets a real, unique id -- generated here, attached
    to the request for handlers to log against, echoed back in a real
    `X-Request-ID` response header, and included in one structured
    "request_completed" log line per request. This is the actual trace
    a real failure gets diagnosed from: given one id from a client
    report or an alert, every log line for that specific request can be
    found, without scanning by timestamp and guessing.
    """
    request.state.request_id = new_request_id()
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        "request_completed",
        extra={
            "event": "request_completed",
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


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


@app.get("/dashboard", response_class=Response)
def dashboard() -> Response:
    """A compact, human-readable view of the few numbers that actually
    reveal whether this system is healthy and whether recommendation
    behavior is drifting (docs/dashboard.md) -- read live from the same
    in-process metric objects `/metrics` exposes, not a second store.
    """
    return Response(content=render_dashboard_html(), media_type="text/html")


@app.get("/demo/{user_id}", response_class=Response)
def demo(user_id: str, num_candidates: int = DEFAULT_NUM_CANDIDATES) -> Response:
    """A real, human-readable trace of one real request through the full
    pipeline (docs/professional-demonstration.md) -- per-stage latency,
    the real ranked slate, real personalization status, and a real
    grounded explanation per item where the evidence supports one.
    Calls the real `recommend()` exactly once; nothing on this page is
    computed a second time for display.
    """
    return Response(content=render_demo_html(user_id, _context(), num_candidates), media_type="text/html")


@app.post("/recommend", response_model=RecommendationResponse)
def recommend_endpoint(payload: RecommendationRequest, http_request: Request) -> RecommendationResponse:
    fell_back = {"value": False}

    def _mark_fallback() -> None:
        fell_back["value"] = True

    stage_timings: dict[str, float] = {}
    start = time.perf_counter()
    try:
        response = safe_recommend(
            payload, _context(), on_fallback=_mark_fallback, stage_timings=stage_timings
        )
    except Exception:
        record_error()
        raise
    record_response(response, is_fallback=fell_back["value"], latency_seconds=time.perf_counter() - start)
    if "feature_lookup_ms" in stage_timings:
        record_feature_lookup_latency(stage_timings["feature_lookup_ms"] / 1000)

    # Quality tracking and structured logging are observability, not
    # correctness: `response` is already a real, valid, fully-computed
    # result, and `record_response` above has already counted it as a
    # success. A bug in this block (a real one existed: a concurrency
    # race in QualitySignalTracker, fixed separately) must never turn
    # that already-successful response into a client-facing 500 --
    # this previously ran with no exception boundary at all, so it
    # could.
    try:
        tracker: QualitySignalTracker = _state["quality_tracker"]
        tracker.record(response)
        update_quality_gauges(tracker.snapshot())

        # The user id is hashed, not logged raw (docs/structured-logging.md):
        # enough for an operator to correlate every log line for one user
        # while debugging, without the real identifier ever sitting in a
        # log file.
        logger.info(
            "recommend_served",
            extra={
                "event": "recommend_served",
                "request_id": getattr(http_request.state, "request_id", None),
                "user_id_hash": hash_user_id(payload.user_id),
                "num_candidates_requested": payload.num_candidates,
                "num_candidates_returned": len(response.recommendations),
                "is_fallback": fell_back["value"],
                "durable_features_used": response.durable_features_used,
                "recent_features_used": response.recent_features_used,
            },
        )
    except Exception:
        logger.exception(
            "Quality tracking or structured logging failed for an otherwise "
            "successful recommendation -- the response is still returned."
        )

    return response
