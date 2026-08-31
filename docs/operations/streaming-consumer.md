# Consume interaction events

The consumer validates Kafka messages, prevents duplicate updates, and
maintains recent user state. The main implementation is
`src/recommender/streaming/consumer.py`. Redis synchronization is in
`src/recommender/features/live_sync.py`.

## Message handling

For each message, the consumer:

1. Parses the JSON and validates the event contract.
2. Rejects an unsupported schema version.
3. Skips an event ID already seen within the active deduplication
   window.
4. Updates user state and monitoring counters.
5. Commits the Kafka offset.

A malformed message is counted and discarded. It does not stop the
consumer.

User state contains:

- the 20 most recent clicked article IDs;
- impressions seen;
- clicks seen; and
- the last event time.

`StreamConsumer` keeps this state only in memory and is intended for
finite verification runs. `SyncingStreamConsumer` writes through to
Redis and uses its in-memory state as a disposable cache.

## Memory limits

The base consumer limits several in-process collections:

| Collection | Limit | Eviction |
|---|---:|---|
| Seen event IDs | 100,000 | Oldest insertion |
| Distinct users | 100,000 | Oldest insertion |
| Distinct articles | 100,000 | Oldest insertion |
| Cached user states | 100,000 | Least recently used |
| Click history per user | 20 | Oldest click |

These limits change how the counters should be read. Distinct-user and
distinct-article values cover the retained window, not the entire life
of a long-running process. The base consumer can also forget an evicted
user's state. The Redis-backed consumer reloads that state when the user
appears again.

## Offset commits

Automatic commits are disabled. `run_consumer()` commits synchronously
after processing each message.

If a commit fails, the consumer tries three times with bounded backoff.
It then stops instead of processing later messages. Kafka commits are
cumulative, so a later successful commit could otherwise hide the
earlier failure.

A new consumer group may return an empty first poll while Kafka assigns
partitions. The loop allows up to five empty polls before the first
message. After consumption has started, an empty poll ends the finite
verification run.

## Restart-safe Redis updates

Redis state mutation and Kafka offset commit are separate operations. A
crash after the Redis write but before the commit causes Kafka to send
the event again.

`claim_and_apply_event()` handles that case with one atomic Lua
operation:

1. Check the event's processed-claim key.
2. If it is new, load the current user state inside Redis, apply the
   event, save the state, and create the claim.
3. If it is already claimed, leave the user unchanged and return the
   current state.

Loading and changing state inside the same operation prevents two
consumers from overwriting each other's updates.

An earlier fix stored the resulting state inside the event claim. On a
duplicate, that design restored the old snapshot and discarded newer
events for the same user. The current operation returns the current
state instead. In other words, a duplicate returns the current state,
not the state recorded when that event first arrived.

Both the processed claim and recent state expire after 24 hours by
default. The idempotency guarantee is therefore bounded: a delivery
after the claim expires is treated as new. The guarantee covers the
Redis feature update, not unrelated side effects that might be added in
the future.

Replay IDs are deterministic, so running the same historical replay
again is also recognized within that retention window.

## Verified run

One broker-backed check consumed the 4,000 events described in the
[replay producer](replay-producer.md):

| Result | Value |
|---|---:|
| Messages polled | 4,000 |
| Newly processed | 4,000 |
| Impressions | 2,000 |
| Clicks | 87 |
| Skips | 1,913 |
| Malformed messages | 0 |
| Duplicates | 0 |
| Retained distinct users | 50 |
| Retained distinct articles | 441 |

These are results from that verification run, not fixed runtime
targets.

See [event contract](event-schema.md),
[state store](state-store.md), and
[recovery testing](recovery-testing.md).
