# Serving cache rules

Each in-process object has an explicit lifetime and refresh rule.

Implementation:
`src/recommender/serving/cache.py`.

## Cached objects

| Cached object | Validity and refresh |
|---|---|
| Two-tower model, content artifact, in-memory Faiss index, ranking model | Loaded together at startup; restart the service after publishing a new validated bundle |
| `DurableFeatureCache` | Reports stale when `data_as_of` is more than 24 hours old; an external batch or operator must call `refresh()` |
| Recent user features | Not cached here; Redis is the current source |

The Faiss index is derived in memory from the loaded model and content
artifact. It is not a separately loaded disk cache.

## Durable feature age

`data_as_of` is the newest source event represented in the cache.
`built_at` is when the process created the cache. Restarting changes
`built_at` but does not make old source data fresh.

MIND data is from November 2019, so the 24-hour threshold is always
exceeded in this research snapshot. `is_stale()` returning `True` is
expected and visible, not evidence that an automated daily job exists.

## Refresh behavior

`is_stale()` only reports age. It does not start offline work from a
request.

`refresh()` builds and returns a new cache instead of mutating an object
already being read. Call it from a scheduled batch or an operator
workflow.

## Why responses are not cached

A saved recommendation would become invalid after a new click changes
recent features. Correct invalidation would have to follow Redis writes
for each user.

Current latency is dominated by retrieval feature building and
reranking, and no measured requirement justifies the added
invalidation system. The service therefore caches artifacts and durable
features, not complete responses.

See [serving latency](../experiments/serving-latency.md),
[online features](online-features.md), and
[health checks](health-checks.md).
