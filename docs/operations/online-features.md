# Online Features

Splits a user's serving-time features into two kinds with genuinely
different refresh requirements, and defines a stable contract for each.
Implementation: `src/recommender/features/online_features.py`.

## The split

- **Durable** (`DurableUserFeatures`) — computed offline, from a user's
  full history up to some cutoff, and refreshed occasionally rather than
  per-event. `compute_durable_features` builds one of these per user from
  their most recent impression's `history` field, since MIND already
  records each user's click history up to that impression's time — the
  latest impression carries the longest available history for that user
  in a given split. Reuses `dominant_category` and `history_ids_from_raw`
  from `ranking/features.py` rather than recomputing the same logic a
  second way. Alongside the two ranking-side summary fields
  (`dominant_category`, `lifetime_click_count`), it also carries
  `history_item_ids` (SERVING-DURABLE-HISTORY-69,
  `docs/engineering-review-register.md`) — the last `MAX_HISTORY` valid
  catalog article ids, in order, bounded the same way the recent-feature
  store bounds a live history. This is a real retrieval-time signal, not
  only a ranking one: `recommender.serving.pipeline.select_retrieval_history`
  falls back to it for the two-tower embedding, Faiss retrieval, and
  content-similarity profile whenever Redis has no usable recent click
  history for that user.
- **Recent** (`RecentUserFeatures`) — must reflect the very latest events.
  `recent_features_from_user_state` adapts the streaming consumer's
  `UserState` (`docs/operations/streaming-consumer.md`) into this stable shape, so
  downstream callers depend on a fixed feature contract instead of the
  consumer's internal representation.

## Why serve them differently

Serving a stale durable feature is an acceptable, deliberate tradeoff — a
user's overall favorite category does not meaningfully shift day to day.
Serving a stale recent feature is a real correctness bug: it would mean a
user's last-clicked items silently exclude everything from the last few
hours, which defeats the point of the streaming work. This is
also what decides where each kind of feature is allowed to live: durable
features stay in the existing offline pandas pipeline; recent features
need a store that can be written and read in milliseconds as events
arrive, which is what the low-latency state store (`docs/operations/state-store.md`)
provides.
