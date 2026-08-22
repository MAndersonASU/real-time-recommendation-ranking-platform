import json
import time
from pathlib import Path

from recommender.features.live_sync import SyncingStreamConsumer
from recommender.features.state_store import build_client, load_recent_features
from recommender.streaming.consumer import run_consumer
from recommender.streaming.kafka_client import (
    DEFAULT_BOOTSTRAP_SERVERS,
    build_producer,
    ensure_topic,
)
from recommender.streaming.schema import EventType, make_event

REPORT_PATH = Path("data/processed/mind_small/live_sync_verification_report.json")


def verify_live_sync(
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
    redis_url: str = "redis://localhost:6379/0",
) -> dict:
    """Publishes real events to a real Kafka topic, consumes them with a
    SyncingStreamConsumer, and confirms the resulting record actually
    landed in the real running Redis -- the full path a live event takes
    from the streaming consumer (`docs/streaming-consumer.md`) through
    the online feature contract (`docs/online-features.md`) into the
    state store (`docs/state-store.md`), exercised end to end against
    real infrastructure.
    """
    topic = f"live-sync-check-{time.time()}".replace(".", "-")
    ensure_topic(topic, bootstrap_servers=bootstrap_servers)
    group_id = f"live-sync-check-group-{time.time()}"

    events = [
        make_event(EventType.IMPRESSION, "U1", "N1", 1, "2019-11-15T08:00:00").to_json().encode(),
        make_event(EventType.CLICK, "U1", "N2", 2, "2019-11-15T08:00:05").to_json().encode(),
        make_event(EventType.CLICK, "U1", "N3", 3, "2019-11-15T08:00:10").to_json().encode(),
    ]
    producer = build_producer(bootstrap_servers)
    for value in events:
        producer.produce(topic, value=value)
    producer.flush(10)

    redis_client = build_client(redis_url)
    stream_consumer = SyncingStreamConsumer(redis_client)
    result = run_consumer(
        stream_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers,
        max_messages=len(events), idle_timeout=5.0,
    )

    stored = load_recent_features(redis_client, "U1")
    in_memory = stream_consumer.user_states["U1"]

    return {
        "messages_processed": result["messages_processed"],
        "redis_record_found": stored is not None,
        "redis_recent_clicked_items": stored.recent_clicked_items if stored else None,
        "redis_matches_in_process_state": (
            stored is not None
            and stored.recent_clicked_items == list(in_memory.recent_clicked_items)
            and stored.impressions_seen == in_memory.impressions_seen
            and stored.clicks_seen == in_memory.clicks_seen
        ),
    }


def main() -> None:
    report = verify_live_sync()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
