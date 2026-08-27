# Live Feature Sync

Wires the streaming consumer to write each user's recent features
straight through to Redis as events arrive, instead of only updating
its own in-process memory. Implementation:
`src/recommender/features/live_sync.py`.

## Overriding `process`, not a hook after the fact

`StreamConsumer.process` (`docs/operations/streaming-consumer.md`)
updates a user's in-process `UserState` on every event, entirely in
memory. `SyncingStreamConsumer` subclasses `StreamConsumer` and
overrides `process` itself, rather than computing state locally first
and pushing it to Redis afterward: each event's own fields are handed
straight to `claim_and_apply_event` (`docs/operations/state-store.md`,
`docs/operations/streaming-consumer.md`), the atomic Lua operation that
loads current state, applies the delta, and writes the claim and state
together. The resulting `RecentUserFeatures` is derived from whatever
that atomic script returns, never from a locally-mutated `UserState`
that could go stale against a concurrent writer.

`SyncingStreamConsumer` also overrides `_get_or_create_state`, so the
first event a fresh process sees for a user restores that user's real
prior state from Redis instead of starting from empty — without it, a
restart would silently roll every user back to zero the moment their
first post-restart event arrived. `_on_state_updated` is overridden too,
but only to a no-op: the base class calls it after mutating its own
in-process state, which is exactly the stale basis this subclass must
not let reach Redis. Parsing, deduplication, and monitoring counters are
inherited from `StreamConsumer` unchanged.

## Verified end to end, against real infrastructure

`verify_live_sync.py` publishes real events to a real Kafka topic,
consumes them with a `SyncingStreamConsumer`, and confirms the resulting
record actually landed in the real running Redis and matches the
in-process state exactly — the full path an event takes from the stream
through the feature contract into the store, exercised against real
Kafka and real Redis rather than assumed from the code alone.
