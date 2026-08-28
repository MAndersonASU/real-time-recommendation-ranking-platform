from prometheus_client import Counter, Gauge, Histogram, Info

from recommender.serving.contract import RecommendationResponse

# HTTP-level, every route and every response: recorded once per request
# by the access-log middleware (recommender.serving.app), independently
# of whether the request ever reached a route handler's own body. This
# is the metric HTTP-METRICS-SCOPE-66 exists to add -- `REQUEST_COUNT`
# below only ever counted a request that reached `/recommend`'s handler
# and passed FastAPI's own request-body validation, so a 422 (malformed
# body, rejected before the handler ever runs) or a middleware-level
# 500 never incremented it despite genuinely being real traffic, and
# `recommend_requests_total`'s own dashboard label ("Total requests")
# overstated what it actually measured.
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Every HTTP response this service sent, by route template, method and status class",
    ["route", "method", "status_class"],
)

# Model-pipeline-level, `/recommend` only: whether a request that
# reached `recommend_endpoint` (past FastAPI's own validation) got a
# real recommendation or the internal error path. Deliberately named
# "attempts", not "requests" -- HTTP_REQUESTS_TOTAL above is the true
# total request count; this one is scoped to valid recommendation
# attempts specifically, so the two can be compared instead of
# conflated (a gap between them is exactly the 4xx/5xx traffic that
# never reached this far).
REQUEST_COUNT = Counter(
    "recommend_requests_total", "Valid /recommend attempts that reached the handler, by outcome", ["outcome"]
)
REQUEST_LATENCY_SECONDS = Histogram(
    "recommend_request_latency_seconds", "End-to-end /recommend latency"
)
CANDIDATE_COUNT = Histogram(
    "recommend_candidate_count", "Number of items actually returned in a response",
    buckets=(0, 1, 5, 10, 20, 50, 100),
)
EMPTY_RESPONSE_COUNT = Counter(
    "recommend_empty_response_total", "Responses that came back with zero recommendations"
)

# Fallback and cache signals: whether real personalization happened,
# derived directly from the response contract's own honesty fields
# (durable_features_used / recent_features_used) rather than a second,
# separately-tracked copy of the same fact.
FALLBACK_COUNT = Counter(
    "recommend_fallback_total", "Responses served by the popularity fallback path", ["reason"]
)
DURABLE_CACHE_COUNT = Counter(
    "recommend_durable_cache_total", "Requests, by whether durable features were found", ["result"]
)
RECENT_CACHE_COUNT = Counter(
    "recommend_recent_cache_total", "Requests, by whether recent (Redis) features were found", ["result"]
)
# Deliberately separate from RECENT_CACHE_COUNT's "miss": a miss there
# also fires for an ordinary user who simply has no recent-events record
# yet, which is not an infrastructure problem. This one only increments
# when Redis itself could not be reached (a real failure, or the circuit
# breaker skipping the attempt) -- the signal an operator actually wants
# to alert on. The request still completed as a real, personalized
# response (recommender.serving.fallback.safe_recommend's on_redis_degraded);
# this is not the same event as FALLBACK_COUNT above.
REDIS_DEGRADED_COUNT = Counter(
    "recommend_redis_degraded_total",
    "Requests where the online feature lookup could not reach Redis, "
    "served anyway with durable features and no recent-features record",
)

# Feature-lookup latency specifically, not just total request time --
# reuses the same stage name the per-stage latency breakdown's
# per-request instrumentation already produces (docs/experiments/serving-latency.md).
FEATURE_LOOKUP_LATENCY_SECONDS = Histogram(
    "recommend_feature_lookup_latency_seconds", "Online feature lookup stage latency"
)

# Kafka lag has a real, honest scope note: the live API never consumes
# from Kafka (docs/operations/restart-and-failure-testing.md confirmed and removed
# that coupling entirely) --
# only the offline streaming consumer processes do. This
# gauge exists as the metric *contract* a running consumer process would
# report into (docs/operations/operational-metrics.md); it has no value here
# because no consumer runs continuously as part of this service.
KAFKA_CONSUMER_LAG = Gauge(
    "recommend_kafka_consumer_lag", "Kafka consumer lag, reported by a running stream consumer"
)


def record_response(
    response: RecommendationResponse,
    *,
    is_fallback: bool,
    latency_seconds: float,
    fallback_reason: str | None = None,
) -> None:
    """Records every operational signal for one real response -- called
    once per `/recommend` request, from the one place a response is
    actually produced, so the metrics can never drift from what was
    really served.
    """
    REQUEST_COUNT.labels(outcome="success").inc()
    REQUEST_LATENCY_SECONDS.observe(latency_seconds)
    CANDIDATE_COUNT.observe(len(response.recommendations))
    if not response.recommendations:
        EMPTY_RESPONSE_COUNT.inc()
    if is_fallback:
        FALLBACK_COUNT.labels(reason=fallback_reason or "unknown").inc()
    DURABLE_CACHE_COUNT.labels(result="hit" if response.durable_features_used else "miss").inc()
    RECENT_CACHE_COUNT.labels(result="hit" if response.recent_features_used else "miss").inc()


def record_error() -> None:
    REQUEST_COUNT.labels(outcome="error").inc()


def record_http_request(route: str, method: str, status_code: int) -> None:
    """Recorded once per HTTP response, for every route -- called from
    the access-log middleware (recommender.serving.app), not from any
    individual route handler, so it can never be skipped by a request
    that never reached one (a 422, or a middleware-level exception).

    `route` is the matched route *template* (e.g. `/demo/{user_id}`,
    from `request.scope["route"].path`), not the resolved path with a
    real id in it -- a raw path would give this counter unbounded label
    cardinality, one series per distinct user or garbage path ever
    requested. An unmatched path (a real 404, no route in this app at
    all) is labeled "unmatched" for the same reason: bounded label
    cardinality regardless of how many distinct nonexistent paths are
    ever hit.
    """
    HTTP_REQUESTS_TOTAL.labels(
        route=route, method=method, status_class=f"{status_code // 100}xx"
    ).inc()


def record_redis_degraded() -> None:
    REDIS_DEGRADED_COUNT.inc()


def record_feature_lookup_latency(seconds: float) -> None:
    FEATURE_LOOKUP_LATENCY_SECONDS.observe(seconds)


# ML quality signals (docs/operations/ml-quality-signals.md): distinct from the
# operational metrics above because a score distribution, diversity
# figure, coverage fraction, or concentration measure only means
# anything computed over many recent responses, never from one request
# in isolation -- see `QualitySignalTracker`, which produces the
# snapshot these gauges are set from.
SCORE_MEAN = Gauge("recommend_score_mean", "Mean recommended-item score over the recent window")
SCORE_P50 = Gauge("recommend_score_p50", "Median recommended-item score over the recent window")
SCORE_P90 = Gauge("recommend_score_p90", "90th-percentile recommended-item score over the recent window")
MEAN_DIVERSITY = Gauge(
    "recommend_mean_diversity", "Mean distinct categories per response over the recent window"
)
CATALOG_COVERAGE = Gauge(
    "recommend_catalog_coverage", "Fraction of the catalog recommended at least once, cumulative"
)
TOP_N_CONCENTRATION = Gauge(
    "recommend_top_n_concentration",
    "Share of all recommendation slots taken by the 10 most-recommended items, cumulative",
)
MODEL_VERSION = Info("recommend_model", "Fingerprint of the currently loaded two-tower model file")


def update_quality_gauges(snapshot: dict) -> None:
    """Sets every quality gauge from one real snapshot. A signal with no
    data yet (`None`) is left at the gauge's last real value rather than
    forced to zero, which would misreport "no signal yet" as "the worst
    possible signal."
    """
    gauge_by_key = {
        "score_mean": SCORE_MEAN,
        "score_p50": SCORE_P50,
        "score_p90": SCORE_P90,
        "mean_diversity": MEAN_DIVERSITY,
        "catalog_coverage": CATALOG_COVERAGE,
        "top_n_concentration": TOP_N_CONCENTRATION,
    }
    for key, gauge in gauge_by_key.items():
        value = snapshot.get(key)
        if value is not None:
            gauge.set(value)


# Offset-commit failures in the streaming consumer. Exposed because a
# failed commit is not a benign retry: Kafka offsets are cumulative, so
# a later successful commit would bury the failed one, and the consumer
# stops rather than risk that. An operator needs to see this rather than
# infer it from a stalled consumer.
COMMIT_FAILURES = Counter(
    "stream_commit_failures_total",
    "Kafka offset commit failures in the streaming consumer",
)


# Age of the *data* behind the durable-feature snapshot, not of the
# process's copy of it. Exposed because the two diverge: restarting the
# service rebuilds the snapshot but does not make a frozen historical
# dataset any newer, and an operator needs the former reported rather
# than the latter.
#
# `data_as_of` (and therefore this age) can genuinely be unknown -- an
# empty behaviors frame has no newest event to measure from
# (`DurableFeatureCache.data_age_seconds`, recommender.serving.cache).
# UNKNOWN-DATA-AGE-67: an earlier version of the one call site that sets
# this gauge (`recommender.serving.app`'s `/ready`) used
# `age_seconds or 0.0`, which silently reported "unknown" as "perfectly
# fresh" -- `None` and a real `0.0` measurement are both falsy in
# Python, so that pattern could not tell them apart. `set_unknown()`
# below sets this to Prometheus's own convention for "no real value,"
# `NaN` -- distinct from every real, non-negative age this gauge can
# otherwise hold -- and DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE makes the
# same fact queryable/alertable without a NaN-aware query.
DURABLE_FEATURE_DATA_AGE = Gauge(
    "durable_feature_data_age_seconds",
    "Seconds between now and the newest event in the durable-feature snapshot; "
    "NaN when that newest-event time is unknown",
)
DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE = Gauge(
    "durable_feature_snapshot_has_known_age",
    "1 if durable_feature_data_age_seconds holds a real measurement, 0 if it is unknown (NaN)",
)


def set_durable_feature_data_age(age_seconds: float | None) -> None:
    if age_seconds is None:
        DURABLE_FEATURE_DATA_AGE.set(float("nan"))
        DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE.set(0)
    else:
        DURABLE_FEATURE_DATA_AGE.set(age_seconds)
        DURABLE_FEATURE_SNAPSHOT_HAS_KNOWN_AGE.set(1)
