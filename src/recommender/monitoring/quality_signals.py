import hashlib
from collections import Counter, deque
from pathlib import Path

from recommender.serving.contract import RecommendationResponse

DEFAULT_WINDOW_SIZE = 500
TOP_N_FOR_CONCENTRATION = 10


class QualitySignalTracker:
    """Real ML quality signals, computed over a bounded rolling window of
    actual recent responses -- distinct from Step 12.1's per-request
    operational counters, since a score distribution, a diversity
    figure, or a concentration measure only means something in
    aggregate, never from a single response alone.
    """

    def __init__(self, catalog_size: int, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        self.catalog_size = catalog_size
        self._scores: deque[float] = deque(maxlen=window_size * 10)
        self._diversity: deque[int] = deque(maxlen=window_size)
        self._recommended_counts: Counter[str] = Counter()

    def record(self, response: RecommendationResponse) -> None:
        for item in response.recommendations:
            self._scores.append(item.score)
            self._recommended_counts[item.news_id] += 1
        distinct_categories = len({item.category for item in response.recommendations if item.category})
        self._diversity.append(distinct_categories)

    def snapshot(self) -> dict:
        """A point-in-time read of every tracked signal. Empty until the
        first real response is recorded -- returns None for anything
        that has no data yet, rather than a misleading zero.
        """
        scores = sorted(self._scores)
        n = len(scores)

        total_recommendations = sum(self._recommended_counts.values())
        top_n_total = sum(count for _, count in self._recommended_counts.most_common(TOP_N_FOR_CONCENTRATION))

        return {
            "score_mean": (sum(scores) / n) if n else None,
            "score_p50": scores[n // 2] if n else None,
            "score_p90": scores[int(n * 0.9)] if n else None,
            "mean_diversity": (sum(self._diversity) / len(self._diversity)) if self._diversity else None,
            "catalog_coverage": (
                len(self._recommended_counts) / self.catalog_size
                if self.catalog_size and total_recommendations
                else None
            ),
            "top_n_concentration": (
                top_n_total / total_recommendations if total_recommendations else None
            ),
        }


def compute_model_version(model_path: Path) -> str:
    """A real, honest stand-in for a formal model version: this project
    has no version registry (docs/experiment-tracking.md's plain log is
    the closest thing), and a retrain overwrites the same file path
    rather than producing a new one. The first 12 hex characters of the
    real file's SHA-256, computed directly from the bytes actually
    loaded, is a genuine fingerprint of exactly which weights are
    serving -- not a fabricated label that could silently drift from
    the real file.
    """
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    return digest[:12]
