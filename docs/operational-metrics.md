# Operational Metrics

Real, live Prometheus-format metrics exposed at `GET /metrics`, recorded
from the one place a response is actually produced. Implementation:
`src/recommender/monitoring/metrics.py`, wired into
`src/recommender/serving/app.py`.

## What's tracked, and why each one is real

- **`recommend_requests_total{outcome}`** — request rate and errors,
  split by success/error.
- **`recommend_request_latency_seconds`** — a histogram, giving real
  p50/p95/p99 from its buckets, not just a mean.
- **`recommend_candidate_count`** — how many items an actual response
  contained; **`recommend_empty_response_total`** — how often that was
  zero.
- **`recommend_fallback_total`** — real fallback rate, driven by a new
  `on_fallback` hook on `safe_recommend()` rather than inferred from the
  response's own feature flags. That distinction matters: a genuine
  cold-start response (Phase 7) can legitimately have both
  `durable_features_used` and `recent_features_used` set to `False`
  without ever touching the fallback path — inferring "fallback" from
  those flags would have conflated two different, real situations.
- **`recommend_durable_cache_total{result}`** /
  **`recommend_recent_cache_total{result}`** — hit/miss rate for each
  feature store, read directly off the response's own honesty flags.
- **`recommend_feature_lookup_latency_seconds`** — the same
  `feature_lookup_ms` stage timing already produced internally by the
  per-stage latency breakdown (`docs/serving-latency.md`),
  now exported as a real, queryable metric via `stage_timings`, which
  `safe_recommend()` forwards straight through to `recommend()`.

## Kafka lag has an honest scope note, not a fabricated number

`recommend_kafka_consumer_lag` exists as a Gauge — the metric *contract*
a running stream consumer would report into — but it has no real value
here, because the live API never consumes from Kafka at request time
(`docs/restart-and-failure-testing.md` confirmed and removed that exact
coupling). Reporting a
number here would mean inventing a value with nothing behind it. The
gauge is the honest version: the shape a real consumer process would
fill in, left at its default until one actually runs continuously as
part of this service.

## A real gap found and fixed while verifying this against the live container

The first real request against the rebuilt container showed
`feature_lookup_latency_seconds_sum` stuck at `0.0` — the metric was
defined but never actually wired to anything. Fixed by adding an
optional `stage_timings` parameter to `safe_recommend()` (the same
opt-in-instrumentation pattern `on_fallback` already uses), forwarded
from the endpoint, and confirmed by rebuilding the container and
sending a second real request: `feature_lookup_latency_seconds_sum`
came back non-zero.
