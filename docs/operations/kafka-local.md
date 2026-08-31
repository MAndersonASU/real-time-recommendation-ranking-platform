# Run Kafka locally

Kafka carries interaction events between the replay producer and the
streaming consumer. The two processes do not call each other directly.

Relevant files:

- `docker-compose.yml`;
- `src/recommender/streaming/kafka_client.py`; and
- `src/recommender/streaming/verify_connectivity.py`.

## Start the broker

Run:

```bash
docker compose up -d kafka
```

The Compose service uses Apache Kafka 3.8.0 in single-node KRaft mode.
For local development, one container acts as both broker and metadata
controller. ZooKeeper is not required.

Wait until the service is healthy:

```bash
docker compose ps
```

The health check calls Kafka's broker API command on port `9092`.

## Client helpers

`kafka_client.py` provides:

- `build_producer()` for publishing messages;
- `build_consumer()` for reading messages; and
- `ensure_topic()` for creating a topic when needed.

The consumer disables automatic offset commits. It commits only after
an event has been processed, which is required for controlled recovery
and duplicate-delivery tests.

## Verify the connection

With Kafka running, execute:

```bash
python -m recommender.streaming.verify_connectivity
```

The command creates a test topic, publishes one message, consumes it,
and compares the received value with the original. It fails when the
broker cannot be reached or the message does not match.

The committed verification report records the topic, broker address,
partition, offset, and comparison result.

See [replay producer](replay-producer.md),
[streaming consumer](streaming-consumer.md), and
[recovery testing](recovery-testing.md).
