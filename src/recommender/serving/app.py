import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from recommender.monitoring.artifact_manifest import (
    build_serving_artifact_manifest,
    compute_serving_version,
)
from recommender.monitoring.dashboard import render_dashboard_html
from recommender.monitoring.metrics import (
    MODEL_VERSION,
    record_error,
    record_feature_lookup_latency,
    record_http_request,
    record_redis_degraded,
    record_response,
    set_durable_feature_data_age,
    update_quality_gauges,
)
from recommender.monitoring.quality_signals import QualitySignalTracker
from recommender.monitoring.structured_logging import (
    configure_structured_logging,
    hash_user_id,
    new_request_id,
)
from recommender.serving.config import load_settings
from recommender.serving.contract import (
    MAX_NUM_CANDIDATES,
    MAX_USER_ID_LENGTH,
    USER_ID_PATTERN,
    RecommendationRequest,
    RecommendationResponse,
)
from recommender.serving.demo import DEFAULT_NUM_CANDIDATES, render_demo_html
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext, build_serving_context

_DEMO_PATH_PATTERN = re.compile(r"^(?P<prefix>/demo/)(?P<user_id>[^/]+?)(?P<suffix>/?)$")


def _loggable_path(path: str) -> str:
    """Redacts the raw user id out of a `/demo/{user_id}` path before it
    reaches a log line -- the access-log middleware below logs
    `request.url.path` verbatim for every route, so this keeps `/demo`
    consistent with `/recommend`'s own explicit log line, which only
    ever logs `hash_user_id(payload.user_id)`. A trailing slash (`/demo/
    U1000/`, which FastAPI redirects but still logs on its own request)
    is matched too, not just the exact no-slash form. Every other
    route's path has no user identifier embedded in it at all, so this
    only needs to special-case `/demo`.
    """
    match = _DEMO_PATH_PATTERN.match(path)
    if match is None:
        return path
    return f"{match.group('prefix')}{hash_user_id(match.group('user_id'))}{match.group('suffix')}"

configure_structured_logging()
logger = logging.getLogger("recommender.serving.app")

_state: dict = {}


def _flatten_manifest(manifest: dict) -> dict[str, str]:
    """Prometheus's `Info` metric needs a flat string-to-string mapping
    -- flattens the manifest's one nested dict (`reranking_config`) and
    stringifies its one list (`ranking_feature_schema`) so the complete
    manifest is visible on `/metrics`, not just the derived version.
    """
    flat: dict[str, str] = {}
    for key, value in manifest.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}_{sub_key}"] = str(sub_value)
        elif isinstance(value, list):
            flat[key] = ",".join(str(item) for item in value)
        else:
            flat[key] = str(value)
    return flat


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads the trained model, index, ranking pipeline, and durable
    cache exactly once at process start -- the same `ServingContext`
    every other real caller (tests, verify_*.py scripts) has already
    used, not a second, app-specific load path.

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
    # The deployed version identifier is derived from the complete
    # serving-artifact manifest (retrieval model, ranking model, feature
    # schema, catalog, embedding model + pinned revision, reranking
    # config) -- not just the retrieval model's own file, which a prior
    # version of this fingerprint used. Changing any one of those
    # artifacts changes this version even if the retrieval model file
    # itself never does (tests/test_artifact_manifest.py proves this
    # directly for each artifact).
    manifest = build_serving_artifact_manifest()
    MODEL_VERSION.info({"serving_version": compute_serving_version(manifest), **_flatten_manifest(manifest)})
    yield
    _state.clear()


app = FastAPI(title="Recommendation Service", lifespan=lifespan)


def _route_template(request: Request) -> str:
    """The matched route's own path template (e.g. `/demo/{user_id}`),
    not the resolved path with a real value in it -- bounded label
    cardinality for HTTP_REQUESTS_TOTAL below, one series per route this
    app actually defines rather than one per distinct value ever seen
    in it. `"unmatched"` for a real 404 (no route in this app matched at
    all), for the same reason: still bounded, regardless of how many
    distinct nonexistent paths are ever requested.
    """
    route = request.scope.get("route")
    return route.path if route is not None else "unmatched"


@app.middleware("http")
async def request_id_and_access_log(request: Request, call_next):
    """Every request gets a real, unique id -- generated here, attached
    to the request for handlers to log against, echoed back in a real
    `X-Request-ID` response header, and included in one structured
    "request_completed" log line per request. This is the actual trace
    a real failure gets diagnosed from: given one id from a client
    report or an alert, every log line for that specific request can be
    found, without scanning by timestamp and guessing.

    Also the one place `HTTP_REQUESTS_TOTAL` is recorded (HTTP-METRICS-SCOPE-66):
    every response this service ever sends passes through here, on
    every route, whether or not it ever reached a route handler's own
    body -- unlike `recommend_requests_total`, which only ever counted a
    request that reached `/recommend`'s handler and passed FastAPI's own
    request-body validation. A malformed request (rejected as a 422
    before any handler runs) or a middleware-level 500 (below) is real
    traffic that metric could never see.
    """
    request.state.request_id = new_request_id()
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # An unhandled exception raised inside a route bypasses this
        # middleware's own return path entirely (call_next itself
        # raises), so without this, neither the X-Request-ID header nor
        # the access log line below ever ran for that request -- an
        # operator diagnosing a real failure from an alert or a client
        # report would have no way to find the matching log line at all.
        # Reconstructs the same request_id/path/duration a completed
        # request already logs; never includes the exception's own
        # message or traceback in the client-facing response.
        duration_ms = (time.perf_counter() - start) * 1000
        record_http_request(route=_route_template(request), method=request.method, status_code=500)
        logger.exception(
            "request_failed",
            extra={
                "event": "request_failed",
                "request_id": request.state.request_id,
                "method": request.method,
                "path": _loggable_path(request.url.path),
                "status_code": 500,
                "duration_ms": round(duration_ms, 2),
            },
        )
        error_response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
        error_response.headers["X-Request-ID"] = request.state.request_id
        return error_response
    duration_ms = (time.perf_counter() - start) * 1000

    response.headers["X-Request-ID"] = request.state.request_id
    record_http_request(
        route=_route_template(request), method=request.method, status_code=response.status_code
    )
    logger.info(
        "request_completed",
        extra={
            "event": "request_completed",
            "request_id": request.state.request_id,
            "method": request.method,
            "path": _loggable_path(request.url.path),
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
    """Readiness, separated from liveness (docs/operations/health-checks.md).
    "Ready" means the model, index, and ranking pipeline actually loaded
    -- the one dependency with no per-request fallback, so a caller
    hitting this service before it finishes loading needs a real 503,
    not a response built from a context that doesn't exist yet.

    Redis is checked too, but reported as a separate, non-fatal
    dependency status rather than failing readiness outright: an
    unreachable Redis degrades one input to an already-running
    pipeline -- recent clicks -- without making the service unable to
    serve a real, personalized response on durable features
    (`docs/operations/serving-fallback.md`), so pulling it out of a load
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
        redis_status = "degraded (durable-features-only personalization)"

    # Feature-snapshot metadata is surfaced here rather than left
    # implicit. Readiness is deliberately not failed on staleness: this
    # project serves a frozen historical snapshot, so a stale-by-design
    # dataset is the expected state, not an outage. An operator sees the
    # real data age instead of having to infer it from a restart time.
    snapshot = context.durable_cache.describe()
    set_durable_feature_data_age(snapshot["data_age_seconds"])

    return {
        "ready": True,
        "dependencies": {"model_index_ranking": "ok", "redis": redis_status},
        "durable_features": snapshot,
    }


@app.get("/metrics")
def metrics() -> Response:
    """Real operational metrics for this process, in Prometheus's own
    text format (docs/operations/operational-metrics.md) -- request rate, errors,
    latency, candidate counts, fallback rate, and durable/recent cache
    hit rates, all recorded from the one place a response is actually
    produced below, never a second, separately-tracked copy.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/dashboard", response_class=Response)
def dashboard() -> Response:
    """A compact, human-readable view of the few numbers that actually
    reveal whether this system is healthy and whether recommendation
    behavior is drifting (docs/operations/dashboard.md) -- read live from the same
    in-process metric objects `/metrics` exposes, not a second store.
    """
    return Response(content=render_dashboard_html(), media_type="text/html")


@app.get("/demo/{user_id}", response_class=Response)
def demo(
    # Same bounds as the JSON request body. A path parameter reaches the
    # same Redis key, hash and log line, so leaving it unbounded here
    # would simply move the problem to a different entry point.
    user_id: str = Path(min_length=1, max_length=MAX_USER_ID_LENGTH, pattern=USER_ID_PATTERN),
    num_candidates: int = Query(DEFAULT_NUM_CANDIDATES, gt=0, le=MAX_NUM_CANDIDATES),
) -> Response:
    """A real, human-readable trace of one real request through the full
    pipeline (docs/professional-demonstration.md) -- per-stage latency,
    the real ranked slate, real personalization status, and a real
    grounded explanation per item where the evidence supports one.
    Calls the real recommendation path exactly once; nothing on this
    page is computed a second time for display.

    `num_candidates`'s bounds are enforced here at the query-parameter
    level, matching `RecommendationRequest`'s own `gt=0, le=MAX_NUM_
    CANDIDATES` constraint -- without it, an out-of-range value would
    pass FastAPI's unconstrained `int` parsing untouched, reach
    `RecommendationRequest` deep inside `build_demo_data`, and raise a
    raw, uncaught pydantic `ValidationError` there: an unhandled 500,
    not the same 422 a request with an equally invalid `/recommend`
    body gets.
    """
    return Response(content=render_demo_html(user_id, _context(), num_candidates), media_type="text/html")


@app.post("/recommend", response_model=RecommendationResponse)
def recommend_endpoint(payload: RecommendationRequest, http_request: Request) -> RecommendationResponse:
    fell_back = {"value": False, "reason": None}
    redis_degraded = {"value": False}

    def _mark_fallback(reason: str) -> None:
        fell_back["value"] = True
        fell_back["reason"] = reason

    def _mark_redis_degraded() -> None:
        redis_degraded["value"] = True

    stage_timings: dict[str, float] = {}
    start = time.perf_counter()
    try:
        response = safe_recommend(
            payload,
            _context(),
            on_fallback=_mark_fallback,
            on_redis_degraded=_mark_redis_degraded,
            stage_timings=stage_timings,
        )
    except Exception:
        record_error()
        raise
    record_response(
        response,
        is_fallback=fell_back["value"],
        fallback_reason=fell_back["reason"],
        latency_seconds=time.perf_counter() - start,
    )
    if redis_degraded["value"]:
        record_redis_degraded()
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

        # The user id is hashed, not logged raw (docs/operations/structured-logging.md):
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
                "fallback_reason": fell_back["reason"],
                "redis_degraded": redis_degraded["value"],
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
