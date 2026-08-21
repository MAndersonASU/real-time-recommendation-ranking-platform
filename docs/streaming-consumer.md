# Streaming Consumer

Turns raw Kafka messages into recent per-user state and global monitoring
counters: validate, deduplicate, transform. Implementation:
`src/recommender/streaming/consumer.py`.

## Three separate jobs, in order

- **Validate** — every message off the broker is just bytes, with no
  guarantee it parses as JSON or matches the current schema. Anything
  that fails to parse or carries the wrong `schema_version` is counted as
  rejected and discarded, never raised — one bad message must never take
  the whole pipeline down.
- **Deduplicate** — Kafka's own delivery guarantees mean a message can
  legitimately arrive more than once (a producer retry, a consumer that
  committed late). The event schema's `event_id` (`docs/event-schema.md`)
  exists specifically for this: a set of every event id already processed
  means a redelivered message updates state exactly zero additional times.
- **Transform** — what survives both checks updates per-user recent state
  (a bounded rolling window of the last 20 clicked items, plus running
  impression/click counts — the same fixed-history idea already used
  offline for the two-tower model's user tower, `docs/retrieval-model.md`,
  now built live from a stream instead of a pre-collected string) and
  global monitoring counters (event counts by type, rejection counts,
  duplicate counts, distinct users/items seen).

State lives entirely in one Python process's memory, deliberately. A
durable, low-latency external store is a separate, later, explicitly
named step of its own; building it here would blur which step is
responsible for what, and validating this consumer's own logic doesn't
need it.

Offsets are committed only after `process()` actually runs on a message,
not the instant it's polled — so a crash between poll and commit leaves
the offset unmoved, and a restarted consumer picks the same message back
up rather than silently skipping it. This is what makes the recovery
testing that follows this step meaningful.

## A real bug, found by testing against a live broker, not assumed away

The first verification run against the real broker reported zero messages
processed even though 4,000 were waiting. Traced directly: the *first*
`poll()` call on a fresh consumer group can return `None` simply because
group/partition assignment hasn't finished yet, not because the topic is
empty — confirmed by polling the same topic by hand and watching the
first call return `None` while every subsequent call succeeded. The
original loop treated any `None` as end-of-stream and broke immediately,
silently skipping the entire backlog. Fixed by only treating `None` as
genuine end-of-stream once at least one real message has already been
received; before that, a bounded number of empty polls are tolerated as
ordinary rebalance warm-up.

## Real result

Consuming the 4,000 events the replay producer published
(`docs/replay-producer.md`), fresh consumer group, from the beginning:

| | |
|---|---|
| Messages polled | 4,000 |
| Messages processed | 4,000 |
| Impressions | 2,000 |
| Clicks | 87 |
| Skips | 1,913 |
| Malformed rejected | 0 |
| Duplicates skipped | 0 |
| Distinct users | 50 |
| Distinct items | 441 |

Exact match to the replay producer's own production counts — nothing
lost, nothing duplicated, on a genuine round trip through a genuine
broker. Verified with 8 unit tests (`tests/test_consumer.py`) covering
validation, schema-version rejection, duplicate suppression, the bounded
recent-items window, and independent per-user state.
