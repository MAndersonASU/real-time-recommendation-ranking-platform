# Operational metrics

`GET /metrics` exposes Prometheus text from
`src/recommender/monitoring/metrics.py`. Metrics are updated by the API
or streaming consumer at the point where the measured event occurs.

## HTTP traffic

| Metric | Meaning |
|---|---|
| `http_requests_total{route,method,status_class}` | Every HTTP response |
| `recommend_requests_total{outcome}` | Valid `/recommend` calls that reached the handler |
| `recommend_request_latency_seconds` | End-to-end recommendation latency |

The HTTP counter uses route templates, such as `/demo/{user_id}`,
instead of resolved paths. Unknown routes use the label `unmatched`.
This prevents a separate metric series for every user ID or bad path.

The recommendation counter is intentionally narrower. Validation errors
that FastAPI rejects before the handler appear in
`http_requests_total` but not `recommend_requests_total`.

## Response behavior

| Metric | Meaning |
|---|---|
| `recommend_candidate_count` | Articles returned per response |
| `recommend_empty_response_total` | Responses with no articles |
| `recommend_fallback_total{reason}` | Responses produced by the popularity fallback |
| `recommend_durable_cache_total{result}` | Durable-feature hit or miss |
| `recommend_recent_cache_total{result}` | Recent-feature hit or miss |
| `recommend_redis_degraded_total` | Requests where Redis was unreachable or skipped by the breaker |
| `recommend_feature_lookup_latency_seconds` | Time spent looking up user features |

A recent-feature miss is not automatically a Redis failure. A user may
simply have no recent record. Redis degradation has its own counter for
that reason.

No-feature and fallback are also different. A valid cold-start response
can use neither durable nor recent features without entering the error
fallback path.

## Durable data age

| Metric | Meaning |
|---|---|
| `durable_feature_data_age_seconds` | Time since the newest event in the durable snapshot |
| `durable_feature_snapshot_has_known_age` | `1` when the age is known, otherwise `0` |

`/ready` updates these gauges. If the source time is unknown, the age is
`NaN` rather than zero. Restarting the API rebuilds the in-memory cache
but does not make the historical data newer.

## Streaming signal

`stream_commit_failures_total` counts Kafka offset commit failures.
The consumer stops after its retry limit, so this counter explains why a
consumer may stop making progress.

`recommend_kafka_consumer_lag` defines a lag gauge, but the API does not
run a Kafka consumer and never updates it. Do not treat its default value
as a measured lag. A continuously deployed consumer would need to set
this gauge from `report_consumer_lag()`.

## Quality signals

The same endpoint also includes score, diversity, coverage,
concentration, and model-version metrics. They summarize multiple
responses and are documented in
[ML quality signals](ml-quality-signals.md).

See [dashboard](dashboard.md), [health checks](health-checks.md), and
[structured logging](structured-logging.md).
