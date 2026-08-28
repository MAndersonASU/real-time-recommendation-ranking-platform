# A Compact Dashboard

One real HTML page, `GET /dashboard`, showing the handful of numbers
that actually reveal whether this system is healthy and whether
recommendation behavior is drifting — not all fifteen-plus metrics
`/metrics` exposes, dumped without curation.
Implementation: `src/recommender/monitoring/dashboard.py`.

## Eleven numbers, not fifty

Recommend attempts, error rate, mean latency, fallback rate,
empty-response rate, durable/recent cache hit rates, mean score, mean
diversity, catalog coverage, and top-10 concentration — read live,
directly from the same in-process Prometheus objects `/metrics` already
exposes, not a second, separately-computed store.

"Recommend attempts" (labeled "Total requests" until HTTP-METRICS-SCOPE-66)
is scoped to valid `/recommend` attempts that reached the handler --
every row on this page is about recommendation behavior, not raw HTTP
traffic, so that scope matches the rest of the page. It is not the
total request count for this service: a malformed request FastAPI
rejects with a 422 before the handler runs, or a middleware-level 500,
is real traffic this row never counted, because `recommend_requests_total`
(what it reads) never saw it either. The true, all-routes total --
every response this service sends, by route template, method and
status class -- is `http_requests_total`, at `/metrics` only; it isn't
curated onto this page because it's an operations signal, not a
recommendation-behavior one.

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
to mean "no data," which is exactly the mistake `docs/operations/ml-quality-signals.md` already caught once for `catalog_coverage` alone.

## Verified against the real running container

Before any request: total requests read `0`, and every other row
correctly showed no data at all. After three real requests: every
number came back real and non-degenerate — 10.9ms mean latency, 66.7%
durable cache hit rate, 2.33 mean diversity, 93.3% top-10
concentration (expected to run high at this small a sample size).
