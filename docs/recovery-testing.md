# Recovery Testing

Everything built earlier in this phase was proven on the happy path — the
broker up, messages well-formed, nothing crashing. This step deliberately
breaks each of those assumptions, for real, against the live broker
brought up in `docs/kafka-local.md`, not simulated in memory.
Implementation: `src/recommender/streaming/recovery.py`,
`src/recommender/streaming/verify_recovery.py`.

Each of the four checks below runs against its own freshly created topic,
so none can interfere with another, and all use the real
`StreamConsumer`/`run_consumer` from `docs/streaming-consumer.md` exactly
as they'd run in production — nothing about the consumer's own code
changes for a test.

## Restart behavior

A consumer processes half a 10-message batch, then is closed mid-stream —
standing in for a real crash. A second, brand-new consumer instance
(fresh in-memory state, same group id) picks up where the first left off.
This only works because offsets commit after processing, not on poll — a
design decision made in the consumer itself, now proven under an actual
restart rather than reasoned about:

| | |
|---|---|
| First run processed | 5 |
| Second run processed | 5 |
| Total across restart | 10 / 10 |
| Lost or reprocessed | none |

## Malformed-event handling

A genuinely broken message (not valid JSON at all) sits between two valid
ones on a real topic:

| | |
|---|---|
| Messages polled | 3 |
| Malformed rejected | 1 |
| Valid events processed | 2 |
| Survived and processed the message after the bad one | yes |

## Duplicate events

The exact same event (same `event_id`) published to the topic twice — a
genuine redelivery, not a repeated in-process call:

| | |
|---|---|
| Messages polled | 2 |
| Duplicates skipped | 1 |
| Distinct events processed | 1 |

## Consumer lag reporting

A new metric introduced at this step: the gap between a topic's latest
offset and what a consumer group has actually committed
(`report_consumer_lag`), using a throwaway `Consumer` bound to the target
group id purely to query watermark and committed offsets — it never
subscribes or polls, so checking lag never disturbs the group's real
position. Measured before consuming, after partially catching up, and
after fully catching up:

| | |
|---|---|
| Lag before consuming | 6 |
| Lag after partial consumption | 3 |
| Lag after full consumption | 0 |

The number moves correctly at each stage and reaches exactly zero once
nothing is left outstanding — a real, working operational signal, not
just a value that happens to print.

## Phase 6 close

**Phase 6 (Event Streaming and Real-Time Interaction Replay) is now fully
complete.** A real local Kafka broker, a schema, a chronologically-paced
replay producer for a reserved historical split, a validating/
deduplicating/transforming consumer, and — this step — proof that all of
it keeps working when the broker rebalances mid-join, a message is
malformed, a message is redelivered, or a consumer crashes and restarts.
Every result above came from an actual running broker, not a mock.
