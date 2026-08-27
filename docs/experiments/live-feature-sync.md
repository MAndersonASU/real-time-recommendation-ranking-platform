# Live Feature Sync

Wires the streaming consumer to write each user's recent features
straight through to Redis as events arrive, instead of only updating
its own in-process memory. Implementation:
`src/recommender/features/live_sync.py`.

## A hook, not a rewrite

`StreamConsumer.process` (`docs/operations/streaming-consumer.md`) already updates a
user's in-process `UserState` on every event. Rather than duplicating
that parsing/dedup/counting logic or coupling the streaming module
directly to Redis, `StreamConsumer` gained one small hook,
`_on_state_updated(user_id, state)`, called right after state changes —
a no-op by default. `SyncingStreamConsumer` subclasses `StreamConsumer`
and overrides only that hook, converting the updated `UserState` into a
`RecentUserFeatures` record (`docs/operations/online-features.md`) and writing it to
Redis (`docs/operations/state-store.md`) via `save_recent_features`. Every other
line of consumer behavior — parsing, deduplication, monitoring counters
— is inherited unchanged.

## Verified end to end, against real infrastructure

`verify_live_sync.py` publishes real events to a real Kafka topic,
consumes them with a `SyncingStreamConsumer`, and confirms the resulting
record actually landed in the real running Redis and matches the
in-process state exactly — the full path an event takes from the stream
through the feature contract into the store, exercised against real
Kafka and real Redis rather than assumed from the code alone.
