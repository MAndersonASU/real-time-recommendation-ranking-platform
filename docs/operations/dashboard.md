# Service dashboard

`GET /dashboard` renders a small HTML summary from the same in-process
Prometheus objects exposed at `GET /metrics`. It does not maintain a
second metric store.

Implementation:
`src/recommender/monitoring/dashboard.py`.

## Displayed values

The page shows 11 indicators:

| Area | Indicators |
|---|---|
| Traffic | Recommendation attempts, error rate |
| Performance | Mean latency |
| Response behavior | Fallback rate, empty-response rate |
| Features | Durable and recent cache hit rates |
| Model output | Mean score, mean diversity, catalog coverage, top-10 concentration |

“Recommendation attempts” means valid `/recommend` requests that reached
the handler. It is not the count of every HTTP request. Use
`http_requests_total` at `/metrics` for all routes, validation failures,
and unmatched paths.

## Why the page shows mean latency

The process can read its histogram's accumulated sum and observation
count, so it can calculate a running mean.

Reliable percentiles require Prometheus to scrape the histogram and
evaluate its buckets over a time window. The dashboard does not invent
a p95 or p99 from one in-process snapshot. Query
`recommend_request_latency_seconds` in Prometheus when percentiles are
needed.

## Missing data

Before recommendation traffic arrives, calculated rates and quality
values appear as an em dash. This distinguishes “not measured yet” from
a real zero.

Prometheus gauges themselves begin at zero, so the renderer uses
request activity to decide when the quality section can be displayed.

## Example verification

One container-backed check produced these values after three requests:

- 10.9 ms mean latency;
- 66.7% durable-feature hit rate;
- 2.33 mean category diversity; and
- 93.3% top-10 concentration.

The high concentration is expected for such a small sample. These
figures demonstrate the page with live data; they are not thresholds or
service targets.

See [operational metrics](operational-metrics.md) and
[ML quality signals](ml-quality-signals.md).
