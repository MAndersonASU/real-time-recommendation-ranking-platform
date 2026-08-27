# ML Quality Signals

signals about the *model's* behavior, computed over a rolling
window of actual recent responses — distinct from the per-request
operational metrics (`docs/operational-metrics.md`), since a score distribution, a
diversity figure, or a concentration measure only means something in
aggregate. Implementation: `src/recommender/monitoring/quality_signals.py`.

## What's tracked

- **Score distribution** (`recommend_score_mean/p50/p90`) — the actual
  spread of scores being returned, over recent individual
  recommendations.
- **Diversity** (`recommend_mean_diversity`) — mean distinct categories
 per response, the same signal reranking's evaluation
  already computed offline, now live.
- **Catalog coverage** (`recommend_catalog_coverage`) — distinct items
  recommended at least once, divided by real catalog size, tracked
  cumulatively rather than windowed (a short window would report
  misleadingly low coverage for a signal that's inherently about the
  long run).
- **Popularity concentration** (`recommend_top_n_concentration`) — the
  share of every recommendation slot ever given out that went to the 10
  most-recommended items. High and rising means the system is leaning
  on a shrinking set of popular items.
- **Model version** (`recommend_model_info{sha256_prefix=...}`) — the
  first 12 hex characters of the real, currently-loaded model file's
  SHA-256, computed directly from the bytes actually loaded. This
  project has no formal model registry (`docs/experiment-tracking.md`'s
  plain log is the closest thing), and a retrain overwrites the same
  file path rather than producing a new one — a real content fingerprint
  is the honest substitute for a version number that doesn't exist.

## Feature missingness lives in `docs/operational-metrics.md`, not duplicated here

Feature missingness is already measured exactly by this project, as
`recommend_durable_cache_total{result}` /
`recommend_recent_cache_total{result}` from the the preceding work. Building
a second, parallel "missingness" signal here would just be the same
fact tracked twice under two different names.

## Regression identified by the tracker's own tests, before real traffic saw it

The first version of `catalog_coverage` returned `0.0` — not `None` —
before any response had ever been recorded, since it only checked that
`catalog_size` was set, not that any data existed yet. A gauge silently
reporting "0% coverage" at startup looks exactly like a real, alarming
signal, when the Interpretation is "no data yet." Caught by a test
(`test_snapshot_is_all_none_before_anything_is_recorded`) written
before the fix, not found in production.
