# Monitor recommendation quality

`QualitySignalTracker` summarizes model output across many successful
responses. It is implemented in
`src/recommender/monitoring/quality_signals.py` and published through
`GET /metrics`.

## Rolling signals

Scores and category diversity use the most recent 500 responses by
default.

| Metric | Meaning |
|---|---|
| `recommend_score_mean` | Mean returned score |
| `recommend_score_p50` | Median returned score |
| `recommend_score_p90` | 90th-percentile returned score |
| `recommend_mean_diversity` | Mean number of distinct categories per response |

The tracker stores each response's score list as one entry. A request
for 50 candidates therefore counts as one response in the window, just
as a request for 10 candidates does.

## Cumulative signals

| Metric | Meaning |
|---|---|
| `recommend_catalog_coverage` | Distinct recommended articles divided by catalog size |
| `recommend_top_n_concentration` | Share of recommendation positions occupied by the 10 most frequent articles |

These values accumulate for the life of the API process. They reset
when the process restarts. A rising concentration can indicate that a
small group of articles is taking more of the available positions.

## Serving version

`recommend_model_info` exposes a 12-character `serving_version` derived
from the complete serving manifest, including:

- retrieval and ranking artifacts;
- ranking feature schema;
- catalog identity;
- embedding model and pinned revision; and
- reranking configuration.

Changing any behavior-affecting field changes the fingerprint. The
metric also exposes the flattened manifest fields so the source of a
version difference can be inspected.

This is a deployed-bundle fingerprint, not a formal model registry.

## Empty and concurrent state

Before any response is recorded, the tracker returns `None` for every
quality value rather than reporting a misleading zero. Gauges update
only when a real value is available.

The API shares one tracker across request worker threads. A lock protects
both updates and snapshots, including iteration over the cumulative
article counter.

## Related signals

Missing durable or recent features are already measured by
`recommend_durable_cache_total` and `recommend_recent_cache_total`.
They are not duplicated under new quality-metric names.

See [operational metrics](operational-metrics.md),
[dashboard](dashboard.md), and
[artifact serving contract](serving-cache.md).
