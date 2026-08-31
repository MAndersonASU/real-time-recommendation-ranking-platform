# Online feature types

Serving combines slower-changing durable features with event-driven
recent features.

Implementation: `src/recommender/features/online_features.py`.

## Contracts

| Type | Fields | Source | Refresh |
|---|---|---|---|
| `DurableUserFeatures` | Dominant category, lifetime click count, bounded history IDs | Offline MIND history | Occasional batch refresh |
| `RecentUserFeatures` | Recent click IDs, impression count, click count, last event time | Streaming events | Per event |

`compute_durable_features` uses the most recent impression history
available for a user in the selected offline split. It reuses ranking
helpers for category and history parsing.

`history_item_ids` keeps the last `MAX_HISTORY` valid catalog IDs in
order. When Redis has no usable clicks, retrieval uses this history for
the user vector, Faiss search, and content profile.

`recent_features_from_user_state` converts streaming `UserState` into a
stable public shape. Downstream code does not depend on the consumer's
internal object.

## Why serve them differently

Durable category preference and lifetime counts can tolerate a planned
refresh interval. Recent clicks cannot: stale recent state would omit
events the online path is meant to capture.

Durable values stay in the offline pandas cache. Recent values live in
Redis for low-latency reads and writes.

See [state store](state-store.md),
[streaming consumer](streaming-consumer.md), and
[cold-start behavior](../experiments/cold-start.md).
