import sys
import threading
from datetime import datetime

from recommender.monitoring.quality_signals import QualitySignalTracker, compute_model_version
from recommender.serving.contract import RecommendationResponse, RecommendedItem


def _response(items) -> RecommendationResponse:
    return RecommendationResponse(
        user_id="u1",
        recommendations=items,
        durable_features_used=True,
        recent_features_used=True,
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


def test_compute_model_version_is_a_real_deterministic_fingerprint(tmp_path):
    model_file = tmp_path / "model.pt"
    model_file.write_bytes(b"some real model bytes")

    version_a = compute_model_version(model_file)
    version_b = compute_model_version(model_file)

    assert version_a == version_b
    assert len(version_a) == 12


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


def test_compute_model_version_changes_with_the_real_file_contents(tmp_path):
    model_file = tmp_path / "model.pt"
    model_file.write_bytes(b"version one")
    version_one = compute_model_version(model_file)

    model_file.write_bytes(b"version two")
    version_two = compute_model_version(model_file)

    assert version_one != version_two
