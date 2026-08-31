# Verify stream recovery

`src/recommender/streaming/verify_recovery.py` checks the consumer
against a running Kafka broker. Each check creates its own topic to
avoid interference from earlier runs.

Run it after starting Kafka:

```bash
python -m recommender.streaming.verify_recovery
```

The command writes `recovery_verification_report.json` to the local
MIND data directory.

## Restart from a committed offset

The verifier publishes 10 messages. One consumer reads five and closes.
A new consumer with the same group ID reads the remaining five.

The published run recorded:

| Result | Value |
|---|---:|
| First consumer | 5 |
| Second consumer | 5 |
| Total | 10 of 10 |

This checks Kafka offset recovery. The second consumer has fresh
in-memory user state; Redis-backed state recovery is covered by the
state-store and live-sync checks.

## Reject a malformed message

The verifier publishes a valid event, invalid JSON, and another valid
event. The consumer must count the bad message and continue:

| Result | Value |
|---|---:|
| Messages polled | 3 |
| Malformed messages | 1 |
| Valid events processed | 2 |

## Skip a duplicate

The same serialized event is published twice. The finite in-memory
consumer should process it once and count one duplicate:

| Result | Value |
|---|---:|
| Messages polled | 2 |
| Duplicates skipped | 1 |
| New events processed | 1 |

This check covers duplicate delivery within one process. Redis-backed
deduplication across a restart is covered separately and is limited by
the processed-claim retention window.

## Report consumer lag

`report_consumer_lag()` compares the latest topic offset with the
consumer group's committed offset. Its temporary client does not
subscribe or poll, so reading lag does not move the group's position.

The published run recorded:

| Point in run | Lag |
|---|---:|
| Before consumption | 6 |
| After three messages | 3 |
| After full consumption | 0 |

## Scope

The broker-backed verifier covers restart position, malformed input,
duplicate input, and lag reporting. Commit failures are tested with
injected client failures because the project does not deliberately
break a live Kafka commit in this check.

The recorded values are evidence from one local run, not service-level
targets. See [streaming consumer](streaming-consumer.md),
[state store](state-store.md), and
[restart and dependency testing](restart-and-failure-testing.md).
