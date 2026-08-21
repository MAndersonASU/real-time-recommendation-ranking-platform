import json
import time
from pathlib import Path

from recommender.streaming.kafka_client import (
    DEFAULT_BOOTSTRAP_SERVERS,
    build_consumer,
    build_producer,
    ensure_topic,
)

REPORT_PATH = Path("data/processed/mind_small/kafka_connectivity_report.json")
TOPIC = "connectivity-check"


def verify_connectivity(bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS) -> dict:
    """Produces one real message to a real broker and consumes it back,
    confirming the value matches exactly. Not a mock -- if no broker is
    reachable at `bootstrap_servers`, this raises rather than reporting a
    false pass.
    """
    ensure_topic(TOPIC, bootstrap_servers=bootstrap_servers)

    producer = build_producer(bootstrap_servers)
    delivery: dict = {}

    def on_delivery(err, msg) -> None:
        if err is None:
            delivery["partition"] = msg.partition()
            delivery["offset"] = msg.offset()

    test_value = f"connectivity-check-{time.time()}".encode()
    producer.produce(TOPIC, value=test_value, callback=on_delivery)
    producer.flush(10)
    if "offset" not in delivery:
        raise RuntimeError("producer never received a delivery confirmation")

    consumer = build_consumer("connectivity-check-group", bootstrap_servers)
    consumer.subscribe([TOPIC])
    received = None
    try:
        for _ in range(20):
            msg = consumer.poll(1.0)
            if msg is not None and msg.error() is None:
                received = msg
                break
    finally:
        consumer.close()

    if received is None:
        raise RuntimeError("consumer never received the message")
    if received.value() != test_value:
        raise RuntimeError("consumed value did not match what was produced")

    return {
        "topic": TOPIC,
        "bootstrap_servers": bootstrap_servers,
        "produced_partition": delivery["partition"],
        "produced_offset": delivery["offset"],
        "consumed_value_matches": True,
    }


def main() -> None:
    report = verify_connectivity()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
