from prometheus_client import Counter, Gauge, Histogram

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
    "recommend_fallback_total", "Responses served by the popularity fallback path"
)
DURABLE_CACHE_COUNT = Counter(
    "recommend_durable_cache_total", "Requests, by whether durable features were found", ["result"]
)
RECENT_CACHE_COUNT = Counter(
    "recommend_recent_cache_total", "Requests, by whether recent (Redis) features were found", ["result"]
)

# Feature-lookup latency specifically, not just total request time --
# reuses the same stage name Step 8.5's per-request instrumentation
# already produces.
FEATURE_LOOKUP_LATENCY_SECONDS = Histogram(
    "recommend_feature_lookup_latency_seconds", "Online feature lookup stage latency"
)

# Kafka lag has a real, honest scope note: the live API never consumes
# from Kafka (Step 11.5 confirmed and removed that coupling entirely) --
# only the offline streaming consumer processes from Phase 6 do. This
# gauge exists as the metric *contract* a running consumer process would
# report into (docs/operational-metrics.md); it has no value here
# because no consumer runs continuously as part of this service.
KAFKA_CONSUMER_LAG = Gauge(
    "recommend_kafka_consumer_lag", "Kafka consumer lag, reported by a running stream consumer"
)


def record_response(response: RecommendationResponse, *, is_fallback: bool, latency_seconds: float) -> None:
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
        FALLBACK_COUNT.inc()
    DURABLE_CACHE_COUNT.labels(result="hit" if response.durable_features_used else "miss").inc()
    RECENT_CACHE_COUNT.labels(result="hit" if response.recent_features_used else "miss").inc()


def record_error() -> None:
    REQUEST_COUNT.labels(outcome="error").inc()


def record_feature_lookup_latency(seconds: float) -> None:
    FEATURE_LOOKUP_LATENCY_SECONDS.observe(seconds)
