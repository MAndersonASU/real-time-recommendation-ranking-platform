# Replay historical interactions

The replay producer publishes MIND's reserved replay split to Kafka as a
timed event stream. Its implementation is
`src/recommender/streaming/replay_producer.py`.

## What it publishes

The producer expands every candidate in an impression into two events:

- one `impression`; and
- one `click` or `skip`, based on MIND's clicked flag.

MIND does not provide a separate click time. Both events therefore use
the original impression time instead of an invented delay.

Events are ordered by timestamp and then impression ID. Kafka messages
are keyed by user ID, so all events for one user remain on the same
partition and keep their production order.

## Replay timing

The producer pauses between rows in proportion to the original time
gap. The `speed` value compresses that wait:

- `3600` means one simulated hour per real second;
- `7200` means two simulated hours per real second.

This preserves relative timing while keeping a local run practical.

## Run it

Start Kafka, then run:

```bash
python -m recommender.streaming.replay_producer
```

The module's default command publishes the first 2,000 ordered
candidate rows at `7200` speed. Call `load_replay_events(limit=None)`
and `replay()` directly when the full expanded split is required.

## Delivery checks

The report distinguishes messages submitted to the producer from
messages confirmed by Kafka. A successful run requires:

- no delivery callback errors;
- no messages left in the local queue after the 30-second flush; and
- a confirmed-delivery count equal to the number produced.

An earlier verification run of the default command recorded:

| Result | Value |
|---|---:|
| Candidate rows replayed | 2,000 |
| Events produced | 4,000 |
| Impressions | 2,000 |
| Clicks | 87 |
| Skips | 1,913 |
| Delivery errors | 0 |

These numbers describe that run, not a fixed property of every replay.
The command writes a fresh `replay_producer_report.json` in the local
MIND data directory.

See [event contract](event-schema.md),
[local Kafka](kafka-local.md), and
[streaming consumer](streaming-consumer.md).
