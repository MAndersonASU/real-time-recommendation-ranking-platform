# A Compact Dashboard

One real HTML page, `GET /dashboard`, showing the handful of numbers
that actually reveal whether this system is healthy and whether
recommendation behavior is drifting — not all fifteen-plus metrics
`/metrics` exposes, dumped without curation.
Implementation: `src/recommender/monitoring/dashboard.py`.

## Eleven numbers, not fifty

Total requests, error rate, mean latency, fallback rate, empty-response
rate, durable/recent cache hit rates, mean score, mean diversity,
catalog coverage, and top-10 concentration — read live, directly from
the same in-process Prometheus objects `/metrics` already exposes, not
a second, separately-computed store.

## An honest substitute for real percentiles

A real p95/p99 needs a query engine evaluating many scrape intervals —
what a real Prometheus server plus PromQL's `histogram_quantile()`
does. This page has no server sitting in front of it scraping over
time; it can only read its own histogram's running sum and count right
now. Reporting a fabricated percentile from a single process's
snapshot would be a number that means something different from
what a p95 normally promises. Mean latency is the honest, simpler
number this page can compute — the full histogram, for real
percentile queries, is still there at `/metrics`.

## Zero is not the same as no data yet, twice over

Two bugs of the same shape were caught before this page ever
served a request: `Histogram` has no direct observation-count
attribute (only `_sum` and per-bucket values), so computing mean
latency from a wrong count would have quietly divided by the wrong
number. And the four Gauge-backed quality signals have no "unset"
state distinct from a real `0.0` — shown only once at least one real
request has actually been recorded, rather than trusting a bare zero
to mean "no data," which is exactly the mistake `docs/ml-quality-signals.md` already caught once for `catalog_coverage` alone.

## Verified against the real running container

Before any request: total requests read `0`, and every other row
correctly showed no data at all. After three real requests: every
number came back real and non-degenerate — 10.9ms mean latency, 66.7%
durable cache hit rate, 2.33 mean diversity, 93.3% top-10
concentration (expected to run high at this small a sample size).
