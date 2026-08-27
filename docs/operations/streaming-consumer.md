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
  committed late). The event schema's `event_id` (`docs/operations/event-schema.md`)
  exists specifically for this: a set of every event id already processed
  means a redelivered message updates state exactly zero additional times.
- **Transform** — what survives both checks updates per-user recent state
  (a bounded rolling window of the last 20 clicked items, plus running
  impression/click counts — the same fixed-history idea already used
  offline for the two-tower model's user tower, `docs/experiments/retrieval-model.md`,
  now built live from a stream instead of a pre-collected string) and
  global monitoring counters (event counts by type, rejection counts,
  duplicate counts, distinct users/items seen).

State lives entirely in one Python process's memory, deliberately. A
durable, low-latency external store is a separate, later, explicitly
named component of its own; building it here would blur which operation is
responsible for what, and validating this consumer's own logic doesn't
need it.

Offsets are committed only after `process()` actually runs on a message,
not the instant it's polled — so a crash between poll and commit leaves
the offset unmoved, and a restarted consumer picks the same message back
up rather than silently skipping it. This is what makes the recovery
testing that follows this check meaningful.

## Restart idempotency: bounded, not absolute

This section describes `SyncingStreamConsumer`
(`recommender.features.live_sync`, `docs/experiments/live-feature-sync.md`),
the Redis-backed subclass built on top of the in-memory `StreamConsumer`
documented above — not the base class itself, which has no restart
guarantee of its own beyond Kafka's offset commit ordering.

The Redis state mutation and the Kafka offset commit are two separate
operations. A crash between them redelivers the message after restart,
and the in-process dedup set (`_seen_event_ids`) does not survive a
restart either, since a new process starts it empty. That combination
once counted the same real click twice.

Neither ordering of the two writes fixes it on its own. Marking the
event processed first can lose its effect entirely if the crash lands
before the state write; writing state first can apply the event twice.
An earlier fix stored the resulting state *inside* the claim key itself
and, on an already-claimed event, restored that stored state — which
rolled the user back to whatever they looked like the moment the
original event was applied, discarding every event processed since.

`claim_and_apply_event` (`recommender.features.state_store`) closes it
with one atomic Lua script that loads current state itself, rather than
trusting a caller-computed value:

1. Check the claim key. If it already exists, the event is a duplicate:
   return the state key's **current** contents, not whatever was stored
   with the original event.
2. Otherwise, load the state key (or start from empty state for a new
   user), apply this event's own delta to it, and write both the claim
   key and the updated state key — all inside the one atomic script.

Because the script derives state from whatever is current *inside*
itself rather than from a value the caller already computed, there is
no stale local basis a concurrent writer could race against. A crash
between polling the message and committing its offset is therefore
self-healing: the redelivery replays the same event against the atomic
script, which recognises the claim and returns the current state
unchanged. Nothing is applied twice and nothing is lost.

The claim carries a TTL rather than accumulating forever, so the
processed-event set stays bounded on its own. That TTL is the real,
remaining bound on the guarantee: a redelivery arriving after it expires
would be treated as new. It is set to a day, far longer than any
realistic restart-and-redelivery window.

### The bound, stated plainly

Atomic event claims provide **bounded** restart and redelivery
idempotency within the configured retention window. Two limits define
that bound, and neither is hidden:

- **The claim expires after 24 hours.** A redelivery arriving later than
  that is treated as new. The window has to exceed the Kafka retention
  and any realistic restart gap to be meaningful; at a day it comfortably
  does for this project's replay-driven workload, but it is a
  configuration value, not a proof.
- **It protects the recent-feature state, not arbitrary side effects.**
  What the claim makes idempotent is the Redis state write. Anything
  else a future consumer might do on an event would need its own
  treatment.

Replay events carry ids derived from their own immutable fields
(`stable_event_id`), so re-running the same historical replay is
idempotent too -- previously those ids were random, and a second replay
of the same day looked like entirely new traffic that no duplicate
detection could recognise.

`tests/test_live_sync.py` covers both halves — that a redelivery does
not double-count, and that the consumer's in-process state is left
correct afterwards so the next genuine event applies on top of the right
value.

## A bug, found by testing against a live broker, not assumed away

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

## Results

Consuming the 4,000 events the replay producer published
(`docs/operations/replay-producer.md`), fresh consumer group, from the beginning:

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
