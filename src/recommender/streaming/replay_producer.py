import json
import time

import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import load_split
from recommender.paths import mind_small_path
from recommender.streaming.kafka_client import (
    DEFAULT_BOOTSTRAP_SERVERS,
    build_producer,
    ensure_topic,
)
from recommender.streaming.schema import EventType, make_event

TOPIC = "interaction-events"
DEFAULT_SPEED = 3600.0  # 1 simulated hour per real second
REPLAY_REPORT_PATH = mind_small_path("replay_producer_report.json")


def order_and_limit(exploded: pd.DataFrame, limit: int | None = None) -> pd.DataFrame:
    """Chronological ordering, ties broken by impression id for a fully
    deterministic replay order. Kept separate from `load_replay_events` so
    the ordering logic is testable without the real (gitignored, licensed)
    dataset.
    """
    ordered = exploded.sort_values(["time", "impression_id"], kind="stable").reset_index(drop=True)
    if limit is not None:
        ordered = ordered.head(limit)
    return ordered


def load_replay_events(limit: int | None = None) -> pd.DataFrame:
    """Chronologically ordered (impression, candidate) rows from the
    reserved `replay` split (docs/experiments/splits.md) -- MIND's
    official dev day, used by the streaming replay producer.
    """
    behaviors = load_split("replay")
    exploded = explode_impressions(behaviors)
    return order_and_limit(exploded, limit)


def sleep_seconds_for_gap(gap_seconds: float, speed: float) -> float:
    """Real-time sleep duration for a simulated gap of `gap_seconds`,
    scaled down by `speed` -- speed=3600 means 1 real second stands in
    for 1 simulated hour. Never negative, even if timestamps are (they
    shouldn't be, given chronological ordering, but a defensive floor
    costs nothing).
    """
    return max(gap_seconds, 0.0) / speed


def events_for_row(row) -> tuple:
    """The two events one exploded (impression, candidate) row produces:
    an impression, always, plus either a click or a derived skip
    (docs/operations/event-schema.md). MIND carries no separate click timestamp, so
    both share the impression's own time rather than fabricating a delay.
    """
    timestamp = row.time.isoformat()
    impression_event = make_event(
        EventType.IMPRESSION, row.user_id, row.news_id, row.impression_id, timestamp
    )
    outcome_type = EventType.CLICK if row.clicked == 1 else EventType.SKIP
    outcome_event = make_event(outcome_type, row.user_id, row.news_id, row.impression_id, timestamp)
    return impression_event, outcome_event


def replay(
    events: pd.DataFrame,
    speed: float = DEFAULT_SPEED,
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
    topic: str = TOPIC,
) -> dict:
    """Publishes `events` in the given (chronological) order, sleeping
    between rows in proportion to the real gap between their original
    timestamps, scaled down by `speed` -- speed=3600 replays a full day
    of history in about 24 real seconds. Never loaded or sent as one
    batch: each row is paced individually against the row before it, and
    every candidate produces two events -- an impression, always, plus
    either a click or a derived skip (docs/operations/event-schema.md) -- since MIND
    carries no separate click timestamp, both share the impression's own
    time rather than fabricating a delay.
    """
    ensure_topic(topic, bootstrap_servers=bootstrap_servers)
    producer = build_producer(bootstrap_servers)

    counts = {"impressions": 0, "clicks": 0, "skips": 0}
    delivery_errors: list = []
    confirmed_delivered = {"n": 0}

    def on_delivery(err, _msg) -> None:
        # Real confluent_kafka never calls this synchronously inside
        # produce() -- it fires later, from poll()/flush(), only once a
        # message's delivery outcome (success or failure) is actually
        # known. `confirmed_delivered` therefore only ever counts real,
        # broker-acknowledged deliveries, never messages merely enqueued.
        if err is not None:
            delivery_errors.append(str(err))
        else:
            confirmed_delivered["n"] += 1

    previous_time = None
    for row in events.itertuples():
        if previous_time is not None:
            gap_seconds = (row.time - previous_time).total_seconds()
            sleep_seconds = sleep_seconds_for_gap(gap_seconds, speed)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        previous_time = row.time

        impression_event, outcome_event = events_for_row(row)
        # Keyed by user_id, not news_id: Kafka only guarantees ordering
        # *within* one partition, and partition assignment is a
        # deterministic function of the key -- keying by item would let
        # two events for the *same user* but *different items* land on
        # different partitions and be processed out of order by a
        # consumer with more than one partition to read from (the
        # default topic has only one partition today, but
        # `ensure_topic`'s `num_partitions` is a real, exposed
        # parameter). `StreamConsumer.process()`
        # accumulates one user's state incrementally (impressions_seen,
        # recent_clicked_items) and depends on seeing that user's own
        # events in their real chronological order -- keying by user_id
        # guarantees every one of a user's events always lands on the
        # same partition, and therefore is always processed in the
        # order they were produced, regardless of partition count.
        producer.produce(
            topic,
            key=row.user_id.encode(),
            value=impression_event.to_json().encode(),
            callback=on_delivery,
        )
        counts["impressions"] += 1

        producer.produce(
            topic,
            key=row.user_id.encode(),
            value=outcome_event.to_json().encode(),
            callback=on_delivery,
        )
        counts["clicks" if outcome_event.event_type is EventType.CLICK else "skips"] += 1

        producer.poll(0)

    # flush(timeout) returns the number of messages still in the local
    # queue when it gives up -- real, undelivered-and-unconfirmed
    # messages, not merely a "did we wait" signal. Discarding this
    # return value (the original bug) meant a real broker stall or
    # outage partway through a run produced a report claiming every
    # event was sent with zero delivery errors, when some were neither
    # confirmed delivered nor reported as failed.
    still_queued_after_flush = producer.flush(30)
    events_produced = sum(counts.values())

    return {
        "topic": topic,
        "speed": speed,
        "rows_replayed": len(events),
        "events_sent": events_produced,
        "events_confirmed_delivered": confirmed_delivered["n"],
        "events_undelivered_after_flush": still_queued_after_flush,
        "impressions_sent": counts["impressions"],
        "clicks_sent": counts["clicks"],
        "skips_sent": counts["skips"],
        "delivery_errors": delivery_errors,
        "all_events_confirmed_delivered": (
            still_queued_after_flush == 0
            and not delivery_errors
            and confirmed_delivered["n"] == events_produced
        ),
    }


def main(limit: int = 2000, speed: float = 7200.0) -> None:
    events = load_replay_events(limit=limit)
    started = time.monotonic()
    report = replay(events, speed=speed)
    report["wall_clock_seconds"] = time.monotonic() - started
    REPLAY_REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
