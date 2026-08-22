import pandas as pd

from recommender.evaluation.evaluate_reranking import (
    _diversity_metrics,
    _freshness_metrics,
    _relevance_metrics,
)


def test_relevance_metrics_hit_rate_reflects_a_click_within_k():
    ordered = pd.DataFrame({"news_id": ["A", "B", "C"], "clicked": [0, 1, 0]})

    result = _relevance_metrics(ordered, k=2, true_relevant_count=1)

    assert result["hit_rate"] == 1.0  # clicked item B is within the top-2


def test_relevance_metrics_hit_rate_zero_when_click_falls_outside_k():
    ordered = pd.DataFrame({"news_id": ["A", "B", "C"], "clicked": [0, 0, 1]})

    result = _relevance_metrics(ordered, k=2, true_relevant_count=1)

    assert result["hit_rate"] == 0.0


def test_relevance_metrics_recall_uses_the_true_total_not_the_slate_alone():
    # The slate only shows one of the impression's real clicks -- the other
    # fell outside the slate entirely and isn't even represented as a row
    # here, the same situation the retrieval evaluation
    # (docs/retrieval-evaluation.md) had to correct for. Passing true_relevant_count=2 must yield recall 0.5,
    # not 1.0 (which is what inferring the total from this slate alone
    # would wrongly give).
    ordered = pd.DataFrame({"news_id": ["A", "B"], "clicked": [1, 0]})

    result = _relevance_metrics(ordered, k=2, true_relevant_count=2)

    assert result["recall"] == 0.5
    assert result["hit_rate"] == 1.0  # hit_rate is correctly unaffected


def test_diversity_metrics_counts_distinct_categories_and_the_dominant_ones_size():
    ordered = pd.DataFrame({"news_id": ["A", "B", "C", "D"]})
    category_by_id = pd.Series({"A": "sports", "B": "sports", "C": "sports", "D": "news"})

    result = _diversity_metrics(ordered, category_by_id)

    assert result["distinct_categories"] == 2
    assert result["max_category_count"] == 3  # 3 sports items dominate


def test_diversity_metrics_on_a_maximally_diverse_slate():
    ordered = pd.DataFrame({"news_id": ["A", "B", "C"]})
    category_by_id = pd.Series({"A": "sports", "B": "news", "C": "tech"})

    result = _diversity_metrics(ordered, category_by_id)

    assert result["distinct_categories"] == 3
    assert result["max_category_count"] == 1


def test_freshness_metrics_computes_mean_age_and_fresh_fraction():
    ordered = pd.DataFrame({"news_id": ["A", "B", "C", "D"], "age_days": [0.1, 0.2, 3.0, 4.0]})

    result = _freshness_metrics(ordered, fresh_threshold_days=0.5, min_fresh_in_slate=2)

    assert result["mean_age_days"] == (0.1 + 0.2 + 3.0 + 4.0) / 4
    assert result["fresh_fraction"] == 0.5  # A and B clear the threshold, C and D don't
    assert result["below_fresh_quota"] is False  # exactly meets the quota of 2


def test_freshness_metrics_flags_a_slate_below_the_quota():
    ordered = pd.DataFrame({"news_id": ["A", "B", "C"], "age_days": [0.1, 3.0, 4.0]})

    result = _freshness_metrics(ordered, fresh_threshold_days=0.5, min_fresh_in_slate=2)

    assert result["below_fresh_quota"] is True  # only 1 fresh item, quota needs 2


def test_freshness_metrics_handles_an_empty_slate_without_crashing():
    ordered = pd.DataFrame({"news_id": [], "age_days": []})

    result = _freshness_metrics(ordered, fresh_threshold_days=0.5, min_fresh_in_slate=2)

    assert result["fresh_fraction"] == 0.0
    assert result["below_fresh_quota"] is True
