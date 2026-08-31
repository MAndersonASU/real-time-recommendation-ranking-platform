# Live feature synchronization

`SyncingStreamConsumer` writes recent user features to Redis as events
arrive. Redis, not process memory, remains the shared state.

Implementation: `src/recommender/features/live_sync.py`.

## Write path

The consumer sends each event's own fields to
`claim_and_apply_event`. That atomic Redis operation:

1. loads the current user state;
2. applies the event;
3. records the processed-event claim; and
4. saves the new state.

The returned Redis state becomes `RecentUserFeatures`. The consumer does
not derive a second state locally and overwrite Redis, which could lose
a concurrent update.

On the first event after a process restart, `_get_or_create_state` loads
the user's existing Redis value instead of starting empty.
`_on_state_updated` is intentionally a no-op because the base class's
local post-update hook must not write stale state back to Redis.

Parsing, duplicate handling, and counters still come from
`StreamConsumer`.

## Verified end to end, against real infrastructure

`verify_live_sync.py` publishes real events to Kafka, consumes them with
`SyncingStreamConsumer`, and reads the final record from Redis. The
stored and returned values must match.

This verifies the full Kafka → consumer → Redis path with real local
services.

See [streaming consumer](../operations/streaming-consumer.md) and
[state store](../operations/state-store.md).
