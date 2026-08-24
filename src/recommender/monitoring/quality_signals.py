import threading
from collections import Counter, deque

from recommender.serving.contract import RecommendationResponse

DEFAULT_WINDOW_SIZE = 500
TOP_N_FOR_CONCENTRATION = 10


class QualitySignalTracker:
    """Real ML quality signals, computed over a bounded rolling window of
    actual recent responses -- distinct from the per-request operational
    counters in `docs/operational-metrics.md`, since a score
    distribution, a diversity figure, or a concentration measure only
    means something in aggregate, never from a single response alone.

    A single instance is shared across every request FastAPI serves,
    and a plain synchronous `def` route runs in a worker thread pool
    (docs/operational-metrics.md), so `record()` and `snapshot()` are
    genuinely called concurrently from multiple real threads, not just
    hypothetically. A real, reproducible race existed here: `record()`
    inserting a never-seen-before `news_id` into `_recommended_counts`
    changes the dict's size, and if that happens while `snapshot()` is
    mid-iteration over the same Counter (via `most_common()`), Python
    raises `RuntimeError: dictionary changed size during iteration` --
    reproduced under real concurrent load, not a theoretical concern.
    `_lock` serializes every mutation and every read against each other.
    """

    def __init__(self, catalog_size: int, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        """`_scores` is bounded by response count, the same way
        `_diversity` already is -- not by a fixed assumption of exactly
        10 recommendations per response. `RecommendationRequest.
        num_candidates` can legitimately be anywhere up to
        `MAX_NUM_CANDIDATES` (50); a caller requesting 50 items per
        response would otherwise fill a flat, per-item-capped window 5x
        faster than one requesting 10, so "window_size" would silently
        stop meaning "the last `window_size` responses" and start
        meaning "the last `window_size // (actual items per response)`
        responses" -- different depending on traffic, with no way for a
        caller to tell. Each response's own score list is stored and
        flattened at `snapshot()` time instead.
        """
        self.catalog_size = catalog_size
        self._scores: deque[list[float]] = deque(maxlen=window_size)
        self._diversity: deque[int] = deque(maxlen=window_size)
        self._recommended_counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def record(self, response: RecommendationResponse) -> None:
        with self._lock:
            self._scores.append([item.score for item in response.recommendations])
            for item in response.recommendations:
                self._recommended_counts[item.news_id] += 1
            distinct_categories = len(
                {item.category for item in response.recommendations if item.category}
            )
            self._diversity.append(distinct_categories)

    def snapshot(self) -> dict:
        """A point-in-time read of every tracked signal. Empty until the
        first real response is recorded -- returns None for anything
        that has no data yet, rather than a misleading zero.
        """
        with self._lock:
            scores = sorted(score for response_scores in self._scores for score in response_scores)
            n = len(scores)

            total_recommendations = sum(self._recommended_counts.values())
            top_n_total = sum(
                count for _, count in self._recommended_counts.most_common(TOP_N_FOR_CONCENTRATION)
            )
            distinct_recommended = len(self._recommended_counts)
            mean_diversity = (sum(self._diversity) / len(self._diversity)) if self._diversity else None

        return {
            "score_mean": (sum(scores) / n) if n else None,
            "score_p50": scores[n // 2] if n else None,
            "score_p90": scores[int(n * 0.9)] if n else None,
            "mean_diversity": mean_diversity,
            "catalog_coverage": (
                distinct_recommended / self.catalog_size
                if self.catalog_size and total_recommendations
                else None
            ),
            "top_n_concentration": (
                top_n_total / total_recommendations if total_recommendations else None
            ),
        }
