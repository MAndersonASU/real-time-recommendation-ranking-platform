from unittest.mock import patch

import pandas as pd

from recommender.streaming.replay_producer import (
    events_for_row,
    order_and_limit,
    replay,
    sleep_seconds_for_gap,
)
from recommender.streaming.schema import EventType


def _exploded(rows):
    return pd.DataFrame(
        {
            "news_id": [r[0] for r in rows],
            "clicked": [r[1] for r in rows],
            "impression_id": [r[2] for r in rows],
            "user_id": [r[3] for r in rows],
            "time": pd.to_datetime([r[4] for r in rows]),
        }
    )


def test_order_and_limit_sorts_chronologically_regardless_of_input_order():
    exploded = _exploded(
        [
            ("N1", 0, 2, "U1", "2019-11-15 10:00:00"),
            ("N2", 1, 1, "U2", "2019-11-15 08:00:00"),
            ("N3", 0, 3, "U3", "2019-11-15 09:00:00"),
        ]
    )

    ordered = order_and_limit(exploded)

    assert list(ordered["impression_id"]) == [1, 3, 2]


def test_order_and_limit_breaks_ties_deterministically_by_impression_id():
    exploded = _exploded(
        [
            ("N1", 0, 5, "U1", "2019-11-15 08:00:00"),
            ("N2", 0, 2, "U2", "2019-11-15 08:00:00"),  # same time as row above
        ]
    )

    ordered = order_and_limit(exploded)

    assert list(ordered["impression_id"]) == [2, 5]  # lower impression_id first


def test_order_and_limit_respects_the_limit():
    exploded = _exploded(
        [
            ("N1", 0, 1, "U1", "2019-11-15 08:00:00"),
            ("N2", 0, 2, "U2", "2019-11-15 09:00:00"),
            ("N3", 0, 3, "U3", "2019-11-15 10:00:00"),
        ]
    )

    ordered = order_and_limit(exploded, limit=2)

    assert len(ordered) == 2
    assert list(ordered["impression_id"]) == [1, 2]


def test_sleep_seconds_for_gap_scales_down_by_speed():
    assert sleep_seconds_for_gap(3600.0, speed=3600.0) == 1.0
    assert sleep_seconds_for_gap(7200.0, speed=3600.0) == 2.0


def test_sleep_seconds_for_gap_never_goes_negative():
    assert sleep_seconds_for_gap(-5.0, speed=3600.0) == 0.0


def test_events_for_row_produces_impression_plus_click_for_a_clicked_candidate():
    exploded = _exploded([("N1", 1, 10, "U1", "2019-11-15 08:00:00")])
    row = next(exploded.itertuples())

    impression_event, outcome_event = events_for_row(row)

    assert impression_event.event_type is EventType.IMPRESSION
    assert outcome_event.event_type is EventType.CLICK
    assert impression_event.timestamp == outcome_event.timestamp  # no fabricated delay
    assert impression_event.item_id == outcome_event.item_id == "N1"


def test_events_for_row_produces_impression_plus_derived_skip_for_a_non_click():
    exploded = _exploded([("N2", 0, 11, "U2", "2019-11-15 09:00:00")])
    row = next(exploded.itertuples())

    _impression_event, outcome_event = events_for_row(row)

    assert outcome_event.event_type is EventType.SKIP


class _StalledProducer:
    """Mimics confluent_kafka.Producer under real backpressure or a
    broker outage partway through a run: produce() enqueues silently
    (real delivery confirmation always arrives later, via poll()/
    flush(), never synchronously inside produce()), and flush(timeout)
    times out with messages still queued and no delivery callback ever
    fired for them.
    """

    def __init__(self):
        self.produced = 0

    def produce(self, topic, key=None, value=None, callback=None):
        self.produced += 1

    def poll(self, timeout=0):
        return 0

    def flush(self, timeout=30):
        return 2  # 2 messages still queued, undelivered, when flush gives up


def test_replay_reports_undelivered_messages_instead_of_claiming_full_success():
    """Regression test for a real bug: replay() discarded flush()'s
    return value (the real count of messages still undelivered when it
    gives up) and reported every enqueued event as sent regardless. This
    fails on the pre-fix code (events_undelivered_after_flush is absent
    and all_events_confirmed_delivered doesn't exist / can't be False)
    and passes once flush's return value is captured and surfaced.
    """
    exploded = _exploded(
        [
            ("N1", 1, 1, "U1", "2019-11-15 08:00:00"),
            ("N2", 0, 2, "U2", "2019-11-15 08:00:01"),
        ]
    )

    with (
        patch("recommender.streaming.replay_producer.ensure_topic"),
        patch("recommender.streaming.replay_producer.build_producer", return_value=_StalledProducer()),
    ):
        report = replay(exploded, speed=999999.0)

    assert report["events_sent"] == 4  # 2 rows x (impression + click/skip) enqueued
    assert report["events_confirmed_delivered"] == 0  # callback never fired -- none confirmed
    assert report["events_undelivered_after_flush"] == 2
    assert report["all_events_confirmed_delivered"] is False
    assert report["delivery_errors"] == []  # no explicit errors either -- just silence, the real risk
