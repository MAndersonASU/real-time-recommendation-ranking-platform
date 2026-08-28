# Operational Metrics

Real, live Prometheus-format metrics exposed at `GET /metrics`, recorded
from the one place a response is produced. Implementation:
`src/recommender/monitoring/metrics.py`, wired into
`src/recommender/serving/app.py`.

## What's tracked, and why each one is real

- **`http_requests_total{route, method, status_class}`** — every HTTP
  response this service ever sends, on every route, recorded once in
  the access-log middleware rather than inside any individual route
  handler (HTTP-METRICS-SCOPE-66) -- so a 422 FastAPI rejects before a
  handler runs, or a middleware-level 500, is still counted here, unlike
  `recommend_requests_total` below. `route` is the matched route
  *template* (`/demo/{user_id}`, not a real resolved user id), and an
  unmatched path is labeled `"unmatched"` -- both keep this counter's
  label cardinality bounded to the routes this app actually defines.
- **`recommend_requests_total{outcome}`** — valid `/recommend` attempts
  that reached the handler (past FastAPI's own request-body validation),
  split by success/error. Deliberately narrower than `http_requests_total`
  above, not a second copy of it: a gap between the two is exactly the
  4xx/5xx traffic that never reached this far.
- **`recommend_request_latency_seconds`** — a histogram, giving real
  p50/p95/p99 from its buckets, not just a mean.
- **`recommend_candidate_count`** — how many items an actual response
  contained; **`recommend_empty_response_total`** — how often that was
  zero.
- **`recommend_fallback_total`** — real fallback rate, driven by a new
  `on_fallback` hook on `safe_recommend()` rather than inferred from the
  response's own feature flags. That distinction matters: a genuine
 cold-start response (the online feature store) can legitimately have both
  `durable_features_used` and `recent_features_used` set to `False`
  without ever touching the fallback path — inferring "fallback" from
  those flags would have conflated two different, real situations.
- **`recommend_durable_cache_total{result}`** /
  **`recommend_recent_cache_total{result}`** — hit/miss rate for each
  feature store, read directly off the response's own honesty flags.
- **`recommend_redis_degraded_total`** — real Redis-outage rate,
  distinct from `recommend_recent_cache_total{result="miss"}` above:
  that miss also fires for an ordinary user who simply has no
  recent-events record yet, which is not an infrastructure problem. This
  counter only increments when Redis itself could not be reached (a
  real failure, or the shared circuit breaker skipping the attempt) --
  driven by the `on_redis_degraded` hook on `safe_recommend()`, the same
  pattern `recommend_fallback_total` above uses
  (`docs/operations/serving-fallback.md`). Not the same event as a
  fallback: the request still completed as a real, personalized
  response on durable features.
- **`recommend_feature_lookup_latency_seconds`** — the same
  `feature_lookup_ms` stage timing already produced internally by the
  per-stage latency breakdown (`docs/experiments/serving-latency.md`),
  now exported as a real, queryable metric via `stage_timings`, which
  `safe_recommend()` forwards straight through to `recommend()`.
- **`durable_feature_data_age_seconds`** — age of the *data* behind the
  durable-feature snapshot (`data_as_of`), set on every `/ready` call
  (`docs/operations/health-checks.md`). `data_as_of` can genuinely be
  unknown (an empty behaviors frame has no newest event to measure
  from), and this reports that as real `NaN`, not a `0.0` that would be
  indistinguishable from a snapshot that is actually zero seconds old
  (UNKNOWN-DATA-AGE-67 -- an earlier version of the one call site that
  sets this used `age_seconds or 0.0`, which folds both cases together
  since both are falsy in Python).
  **`durable_feature_snapshot_has_known_age`** is the same fact as a
  plain 0/1, so "is the age known at all" is queryable/alertable
  without a NaN-aware query.

## Kafka lag has an honest scope note, not a fabricated number

`recommend_kafka_consumer_lag` exists as a Gauge — the metric *contract*
a running stream consumer would report into — but it has no value
here, because the live API never consumes from Kafka at request time
(`docs/operations/restart-and-failure-testing.md` confirmed and removed that exact
coupling). Reporting a
number here would mean inventing a value with nothing behind it. The
gauge is the honest version: the shape a real consumer process would
fill in, left at its default until one actually runs continuously as
part of this service.

## A gap found and fixed while verifying this against the live container

The first real request against the rebuilt container showed
`feature_lookup_latency_seconds_sum` stuck at `0.0` — the metric was
defined but never actually wired to anything. Fixed by adding an
optional `stage_timings` parameter to `safe_recommend()` (the same
opt-in-instrumentation pattern `on_fallback` already uses), forwarded
from the endpoint, and confirmed by rebuilding the container and
sending a second real request: `feature_lookup_latency_seconds_sum`
came back non-zero.
