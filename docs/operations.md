# Operations

How the system runs: streaming, serving, observability and containers.
Detail lives under [`docs/operations/`](operations/); this page is the map.

There is no production deployment. Everything below describes a local
containerized stack and the code paths it exercises.

## Serving

The API loads a versioned artifact bundle read-only and validates every
member's checksum at startup. It needs Redis for recent user state; it
does not need Kafka at request time.

- [`serving-contract.md`](operations/serving-contract.md) — request and response types
- [`inference-path.md`](operations/inference-path.md) — retrieval, ranking and reranking in one request
- [`serving-fallback.md`](operations/serving-fallback.md) — what happens when a stage fails
- [`serving-cache.md`](operations/serving-cache.md) — what is cached, and how stale it can be
- [`health-checks.md`](operations/health-checks.md) — liveness and readiness
- [`configuration.md`](operations/configuration.md) — settings and their defaults

## Streaming

Historical interaction replay through Kafka into a validating,
deduplicating consumer that maintains recent user state in Redis.

- [`event-schema.md`](operations/event-schema.md) — the event contract
- [`kafka-local.md`](operations/kafka-local.md) — running a broker locally
- [`replay-producer.md`](operations/replay-producer.md) — chronologically paced replay
- [`streaming-consumer.md`](operations/streaming-consumer.md) — validation, deduplication, offset handling
- [`online-features.md`](operations/online-features.md) — durable and recent features
- [`state-store.md`](operations/state-store.md) — the Redis layer

## Failure behaviour

- [`recovery-testing.md`](operations/recovery-testing.md) — rebalance, malformed message, redelivery, consumer restart
- [`restart-and-failure-testing.md`](operations/restart-and-failure-testing.md) — container restart paths

Commit-failure behaviour against a live broker is **not** fully verified.
That gap is recorded as STREAM-COMMIT-04 in the
[review register](engineering-review-register.md), partially closed by an
explicit scope decision.

## Observability

- [`operational-metrics.md`](operations/operational-metrics.md) — latency, throughput, error rate
- [`ml-quality-signals.md`](operations/ml-quality-signals.md) — quality signals distinct from operational health
- [`structured-logging.md`](operations/structured-logging.md) — request-correlated JSON logs
- [`dashboard.md`](operations/dashboard.md) — the compact operator view

## Containers and CI

- [`containerization.md`](operations/containerization.md) — image, compose stack, non-root user
- [`ci-automation.md`](operations/ci-automation.md) — the four jobs and what each proves

CI runs on pushes to `main` and pull requests targeting `main`. It
exercises the container against synthetic artifacts only; it reproduces no
published number.
