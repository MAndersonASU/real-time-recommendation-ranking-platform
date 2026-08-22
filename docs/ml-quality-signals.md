# ML Quality Signals

Real signals about the *model's* behavior, computed over a rolling
window of actual recent responses — distinct from Step 12.1's
per-request operational metrics, since a score distribution, a
diversity figure, or a concentration measure only means something in
aggregate. Implementation: `src/recommender/monitoring/
quality_signals.py`.

## What's tracked

- **Score distribution** (`recommend_score_mean/p50/p90`) — the actual
  spread of scores being returned, over recent individual
  recommendations.
- **Diversity** (`recommend_mean_diversity`) — mean distinct categories
  per response, the same real signal Phase 5's reranking evaluation
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

## Feature missingness lives in Step 12.1, not duplicated here

The guide's own list for this step includes feature missingness — this
project already measures that exactly, as
`recommend_durable_cache_total{result}` /
`recommend_recent_cache_total{result}` from the previous step. Building
a second, parallel "missingness" signal here would just be the same
fact tracked twice under two different names.

## A real bug caught by the tracker's own tests, before real traffic saw it

The first version of `catalog_coverage` returned `0.0` — not `None` —
before any response had ever been recorded, since it only checked that
`catalog_size` was set, not that any data existed yet. A gauge silently
reporting "0% coverage" at startup looks exactly like a real, alarming
signal, when the honest answer is "no data yet." Caught by a test
(`test_snapshot_is_all_none_before_anything_is_recorded`) written
before the fix, not found in production.
