from prometheus_client import Counter, Gauge, Histogram, Info

from recommender.serving.contract import RecommendationResponse

# Request-level: rate, errors, latency, and slate shape -- the core
# signals for "is this service working and how fast."
REQUEST_COUNT = Counter(
    "recommend_requests_total", "Total /recommend requests, by outcome", ["outcome"]
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

# Feature-lookup latency specifically, not just total request time --
# reuses the same stage name the per-stage latency breakdown's
# per-request instrumentation already produces (docs/experiments/serving-latency.md).
FEATURE_LOOKUP_LATENCY_SECONDS = Histogram(
    "recommend_feature_lookup_latency_seconds", "Online feature lookup stage latency"
)

# Kafka lag has a real, honest scope note: the live API never consumes
# from Kafka (docs/operations/restart-and-failure-testing.md confirmed and removed
# that coupling entirely) --
# only the offline streaming consumer processes from Phase 6 do. This
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
DURABLE_FEATURE_DATA_AGE = Gauge(
    "durable_feature_data_age_seconds",
    "Seconds between now and the newest event in the durable-feature snapshot",
)
