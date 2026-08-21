import json
import time
from pathlib import Path

from recommender.streaming.consumer import StreamConsumer, run_consumer
from recommender.streaming.kafka_client import (
    DEFAULT_BOOTSTRAP_SERVERS,
    build_producer,
    ensure_topic,
)
from recommender.streaming.recovery import report_consumer_lag
from recommender.streaming.schema import EventType, make_event

RECOVERY_REPORT_PATH = Path("data/processed/mind_small/recovery_verification_report.json")


def _fresh_topic(prefix: str) -> str:
    return f"recovery-{prefix}-{time.time()}".replace(".", "-")


def _publish(events: list, bootstrap_servers: str, topic: str) -> None:
    producer = build_producer(bootstrap_servers)
    for value in events:
        producer.produce(topic, value=value)
    producer.flush(10)


def verify_restart_resumes_from_committed_offset(
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
) -> dict:
    """A consumer processes half a batch, then is closed (simulating a
    crash) before the rest is touched. A second, brand-new consumer
    instance -- same group id, fresh in-memory state, standing in for a
    real process restart -- must pick up exactly where the first left
    off: no message reprocessed, none lost.
    """
    topic = _fresh_topic("restart")
    ensure_topic(topic, bootstrap_servers=bootstrap_servers)
    group_id = f"restart-check-{time.time()}"

    events = [
        make_event(EventType.CLICK, "U1", f"N{i}", i, "t").to_json().encode() for i in range(10)
    ]
    _publish(events, bootstrap_servers, topic)

    first_consumer = StreamConsumer()
    first_result = run_consumer(
        first_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers,
        max_messages=5, idle_timeout=5.0,
    )

    second_consumer = StreamConsumer()  # fresh state -- simulates a real restart
    second_result = run_consumer(
        second_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers, idle_timeout=3.0
    )

    total_processed = first_result["messages_processed"] + second_result["messages_processed"]
    return {
        "first_run_processed": first_result["messages_processed"],
        "second_run_processed": second_result["messages_processed"],
        "total_processed_across_restart": total_processed,
        "expected_total": len(events),
        "no_message_lost_or_reprocessed": total_processed == len(events),
    }


def verify_malformed_events_dont_crash_the_consumer(
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
) -> dict:
    """A malformed message sits between two valid ones on a real topic.
    The consumer must reject it, keep running, and still process the
    valid message that comes after it.
    """
    topic = _fresh_topic("malformed")
    ensure_topic(topic, bootstrap_servers=bootstrap_servers)
    group_id = f"malformed-check-{time.time()}"

    valid_before = make_event(EventType.CLICK, "U1", "N1", 1, "t").to_json().encode()
    malformed = b"{not valid json at all"
    valid_after = make_event(EventType.CLICK, "U2", "N2", 2, "t").to_json().encode()
    _publish([valid_before, malformed, valid_after], bootstrap_servers, topic)

    stream_consumer = StreamConsumer()
    result = run_consumer(
        stream_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers,
        max_messages=3, idle_timeout=5.0,
    )

    return {
        "messages_polled": result["messages_polled"],
        "malformed_rejected": stream_consumer.counters.malformed_rejected,
        "valid_events_processed": stream_consumer.counters.total_processed,
        "consumer_survived_and_processed_the_message_after_the_bad_one": (
            stream_consumer.counters.total_processed == 2
        ),
    }


def verify_duplicate_events_are_suppressed(
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
) -> dict:
    """The exact same event (same event_id) published twice to a real
    topic -- a genuine redelivery scenario, not simulated in memory.
    """
    topic = _fresh_topic("duplicate")
    ensure_topic(topic, bootstrap_servers=bootstrap_servers)
    group_id = f"duplicate-check-{time.time()}"

    raw = make_event(EventType.CLICK, "U1", "N1", 1, "t").to_json().encode()
    _publish([raw, raw], bootstrap_servers, topic)

    stream_consumer = StreamConsumer()
    result = run_consumer(
        stream_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers,
        max_messages=2, idle_timeout=5.0,
    )

    return {
        "messages_polled": result["messages_polled"],
        "duplicates_skipped": stream_consumer.counters.duplicates_skipped,
        "distinct_events_processed": stream_consumer.counters.total_processed,
    }


def verify_consumer_lag_reporting(bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS) -> dict:
    """Lag measured before consuming (nothing committed yet), after
    partially consuming a batch, and after fully catching up -- confirming
    the number actually moves and reaches exactly zero once caught up.
    """
    topic = _fresh_topic("lag")
    ensure_topic(topic, bootstrap_servers=bootstrap_servers)
    group_id = f"lag-check-{time.time()}"

    events = [
        make_event(EventType.CLICK, "U1", f"N{i}", i, "t").to_json().encode() for i in range(6)
    ]
    _publish(events, bootstrap_servers, topic)

    lag_before = report_consumer_lag(group_id, topic, bootstrap_servers=bootstrap_servers)

    stream_consumer = StreamConsumer()
    run_consumer(
        stream_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers,
        max_messages=3, idle_timeout=5.0,
    )
    lag_after_partial = report_consumer_lag(group_id, topic, bootstrap_servers=bootstrap_servers)

    run_consumer(stream_consumer, group_id, topic=topic, bootstrap_servers=bootstrap_servers, idle_timeout=3.0)
    lag_after_full = report_consumer_lag(group_id, topic, bootstrap_servers=bootstrap_servers)

    return {
        "lag_before_consuming": lag_before[0]["lag"],
        "lag_after_partial_consumption": lag_after_partial[0]["lag"],
        "lag_after_full_consumption": lag_after_full[0]["lag"],
    }


def verify_recovery() -> dict:
    return {
        "restart_behavior": verify_restart_resumes_from_committed_offset(),
        "malformed_event_handling": verify_malformed_events_dont_crash_the_consumer(),
        "duplicate_event_handling": verify_duplicate_events_are_suppressed(),
        "consumer_lag_reporting": verify_consumer_lag_reporting(),
    }


def main() -> None:
    report = verify_recovery()
    RECOVERY_REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
