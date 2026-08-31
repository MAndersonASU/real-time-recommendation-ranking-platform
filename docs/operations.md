# Operations

This page points to the runtime documentation. The project has no
production deployment; these pages describe the local container stack,
the API, Kafka replay, Redis state, and the checks run in CI.

## Run or inspect the API

| Need | Document |
|---|---|
| Request and response fields | [Serving contract](operations/serving-contract.md) |
| What one recommendation request does | [Inference path](operations/inference-path.md) |
| Behavior during known dependency failures | [Serving fallback](operations/serving-fallback.md) |
| Cache contents and freshness | [Serving cache](operations/serving-cache.md) |
| `/health` and `/ready` behavior | [Health checks](operations/health-checks.md) |
| Settings and defaults | [Configuration](operations/configuration.md) |

At startup, the API validates its artifact bundle and loads it
read-only. Redis supplies recent user behavior but is not required for
the API to answer. Kafka is not part of the request path.

## Run or inspect streaming

| Need | Document |
|---|---|
| Event fields and validation | [Event schema](operations/event-schema.md) |
| Local Kafka setup | [Kafka locally](operations/kafka-local.md) |
| Historical event replay | [Replay producer](operations/replay-producer.md) |
| Validation, deduplication, and offsets | [Streaming consumer](operations/streaming-consumer.md) |
| Durable and recent user data | [Online features](operations/online-features.md) |
| Redis storage behavior | [State store](operations/state-store.md) |

Historical events are replayed through Kafka. The consumer validates
them, ignores duplicates within the retention window, and updates recent
user state in Redis.

## Diagnose failures

- [Recovery testing](operations/recovery-testing.md) covers malformed
  messages, redelivery, rebalances, and consumer restarts.
- [Restart and failure testing](operations/restart-and-failure-testing.md)
  covers stopped services, missing artifacts, and container restarts.

Commit failure against a live Kafka broker is not fully verified. The
review register records this as `STREAM-COMMIT-04`, partially closed by
scope.

## Observe the service

| Need | Document |
|---|---|
| Latency, throughput, errors, and cache metrics | [Operational metrics](operations/operational-metrics.md) |
| Recommendation-quality indicators | [ML quality signals](operations/ml-quality-signals.md) |
| Request-correlated JSON logs | [Structured logging](operations/structured-logging.md) |
| Compact operator view | [Dashboard](operations/dashboard.md) |

Operational health and recommendation quality are separate. A healthy
API can still serve poor recommendations, so the project reports both.

## Build and verify containers

- [Containerization](operations/containerization.md) describes the
  image, Compose services, health checks, and non-root user.
- [CI automation](operations/ci-automation.md) explains the four
  GitHub Actions jobs and what each proves.

CI uses synthetic artifacts to test wiring and contracts. It does not
download MIND or reproduce any licensed-data quality result.
