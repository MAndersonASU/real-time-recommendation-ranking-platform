# Running Kafka Locally

A real message broker, brought up in Docker, that the replay producer and
the streaming consumer (built next in this phase) talk to independently
through — neither ever calls the other directly. Implementation:
`docker-compose.yml`,
`src/recommender/streaming/kafka_client.py`,
`src/recommender/streaming/verify_connectivity.py`.

## Setup

Single-node Kafka in KRaft mode (`apache/kafka:3.8.0`) — one broker
container acting as its own metadata controller, rather than the classic
Kafka-plus-Zookeeper pair. KRaft is modern Kafka's own built-in
replacement for Zookeeper: one moving part instead of two, with nothing
lost for a single-node local setup. The same complexity-boundary judgment
already applied throughout this project — the simpler, modern option when
it's genuinely equivalent for the actual need.

Bring up: `docker compose up -d`. Health-checked via
`kafka-broker-api-versions.sh` until the container reports `healthy`
before anything tries to connect.

`kafka_client.py` provides three small, reusable helpers every later
Phase 6 component builds on: `build_producer`, `build_consumer` (manual
offset commits — `enable.auto.commit: False` — deliberately, since Step
6.5's recovery tests need direct control over exactly when an offset
counts as processed), and `ensure_topic`.

## Real verification, not assumed

`verify_connectivity.py` produces one real message to a real topic on a
real running broker and consumes it back, raising rather than reporting a
false pass if no broker is reachable. Real result:

```json
{
  "topic": "connectivity-check",
  "bootstrap_servers": "localhost:9092",
  "produced_partition": 0,
  "produced_offset": 0,
  "consumed_value_matches": true
}
```

Nothing here is mocked — a genuine round trip through a genuine separate
process (Docker Desktop started, healthcheck polled to `healthy`, message
delivered and confirmed, then read back and compared byte-for-byte),
reproducible via `python -m recommender.streaming.verify_connectivity`
with a broker running.
