import sys
import threading
from datetime import datetime

from recommender.monitoring.quality_signals import QualitySignalTracker
from recommender.serving.contract import RecommendationResponse, RecommendedItem


def _response(items) -> RecommendationResponse:
    return RecommendationResponse(
        user_id="u1",
        recommendations=items,
        durable_features_used=True,
        recent_features_used=True,
        retrieval_history_source="recent",
        generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001
    )


def test_snapshot_is_all_none_before_anything_is_recorded():
    tracker = QualitySignalTracker(catalog_size=100)

    snapshot = tracker.snapshot()

    assert all(value is None for value in snapshot.values())


def test_score_stats_reflect_real_recorded_scores():
    tracker = QualitySignalTracker(catalog_size=100)
    tracker.record(_response([
        RecommendedItem(news_id="n1", score=0.2, rank=1, category="sports"),
        RecommendedItem(news_id="n2", score=0.8, rank=2, category="tech"),
    ]))

    snapshot = tracker.snapshot()

    assert snapshot["score_mean"] == 0.5


def test_mean_diversity_counts_distinct_categories_per_response():
    tracker = QualitySignalTracker(catalog_size=100)
    tracker.record(_response([
        RecommendedItem(news_id="n1", score=0.5, rank=1, category="sports"),
        RecommendedItem(news_id="n2", score=0.5, rank=2, category="sports"),
        RecommendedItem(news_id="n3", score=0.5, rank=3, category="tech"),
    ]))

    assert tracker.snapshot()["mean_diversity"] == 2


def test_catalog_coverage_is_distinct_items_over_catalog_size():
    tracker = QualitySignalTracker(catalog_size=10)
    tracker.record(_response([
        RecommendedItem(news_id="n1", score=0.5, rank=1),
        RecommendedItem(news_id="n1", score=0.5, rank=1),  # same item again, a second response
        RecommendedItem(news_id="n2", score=0.5, rank=2),
    ]))

    assert tracker.snapshot()["catalog_coverage"] == 2 / 10


def test_top_n_concentration_is_one_when_everything_is_the_same_item():
    tracker = QualitySignalTracker(catalog_size=10)
    for _ in range(5):
        tracker.record(_response([RecommendedItem(news_id="n1", score=0.5, rank=1)]))

    assert tracker.snapshot()["top_n_concentration"] == 1.0


def test_score_window_holds_the_same_number_of_responses_regardless_of_response_size():
    """Regression test for a real bug, found by audit: the score window
    used to be a flat deque of individual item scores capped at
    `window_size * 10` -- a hardcoded assumption of exactly 10
    recommendations per response, even though `num_candidates` can
    legitimately be up to 50 (`MAX_NUM_CANDIDATES`). A caller requesting
    50 items per response filled that capacity 5x faster than one
    requesting 10, so "window_size" silently represented far fewer real
    responses than intended, depending on traffic. Fails on the pre-fix
    code (a 50-item-per-response window only remembers a fraction of
    `window_size` responses) and passes once the window is bounded by
    response count, matching how `_diversity` already worked correctly.
    """
    window_size = 5
    tracker = QualitySignalTracker(catalog_size=1000, window_size=window_size)

    # More responses than the window holds, each with 50 items (the real
    # maximum, not the 10-per-response assumption the old code baked in).
    for i in range(window_size + 3):
        items = [
            RecommendedItem(news_id=f"n{i}_{j}", score=0.5, rank=j + 1) for j in range(50)
        ]
        tracker.record(_response(items))

    snapshot = tracker.snapshot()
    total_scores_in_window = window_size * 50
    assert snapshot["score_mean"] == 0.5  # sanity: every recorded score really is 0.5
    # The internal window must remember exactly `window_size` responses'
    # worth of scores, not fewer -- checked directly against the private
    # state, since the public snapshot alone (all scores equal to 0.5
    # here) can't distinguish "5 responses of 50" from "1 response of 50".
    assert sum(len(response_scores) for response_scores in tracker._scores) == total_scores_in_window
    assert len(tracker._scores) == window_size


def test_tracker_survives_real_concurrent_record_and_snapshot_calls():
    """Regression test for a real, reproduced concurrency bug: `record()`
    inserting a never-seen-before news_id into the internal Counter
    changes its size, and if that happens while `snapshot()` is
    mid-iteration over the same Counter (via most_common()), Python
    raises `RuntimeError: dictionary changed size during iteration`.
    Reproduced with 100% failure under real thread contention before the
    fix (a lock around every mutation and every read). A short switch
    interval forces frequent real GIL handoffs so the race window is
    actually exercised within a fast, deterministic test, not left to
    chance timing.
    """
    original_interval = sys.getswitchinterval()
    sys.setswitchinterval(0.00001)
    try:
        tracker = QualitySignalTracker(catalog_size=100_000)
        errors: list[Exception] = []
        stop = threading.Event()

        def hammer_record(thread_id: int) -> None:
            n = 0
            while not stop.is_set():
                response = _response(
                    [RecommendedItem(news_id=f"t{thread_id}_{n}", score=0.5, rank=1)]
                )
                try:
                    tracker.record(response)
                except Exception as exc:  # noqa: BLE001 -- capturing for the assertion below
                    errors.append(exc)
                    break
                n += 1

        def hammer_snapshot() -> None:
            for _ in range(3000):
                try:
                    tracker.snapshot()
                except Exception as exc:  # noqa: BLE001 -- capturing for the assertion below
                    errors.append(exc)
                    break

        writers = [threading.Thread(target=hammer_record, args=(i,)) for i in range(8)]
        for writer in writers:
            writer.start()
        hammer_snapshot()
        stop.set()
        for writer in writers:
            writer.join()
    finally:
        sys.setswitchinterval(original_interval)

    assert errors == []
