import pandas as pd

from recommender.evaluation.evaluate_ranking import _evaluate_by_score


def _rows(pairs):
    return pd.DataFrame(
        {
            "impression_id": [p[0] for p in pairs],
            "news_id": [p[1] for p in pairs],
            "clicked": [p[2] for p in pairs],
            "score": [p[3] for p in pairs],
        }
    )


def test_orders_by_descending_score_with_deterministic_tie_break():
    rows = _rows(
        [
            (1, "B", 0, 0.5),
            (1, "A", 1, 0.5),  # tied with B -- news_id break puts A ahead of B
            (1, "C", 0, 0.9),
        ]
    )

    result = _evaluate_by_score(rows, "score", k=2, catalog_size=10)

    # Order: C(0.9), then A before B (tie broken by news_id) -> clicked A is
    # at rank 2, inside the top-2 -> hit.
    assert result["hit_rate_at_k"] == 1.0


def test_hit_rate_is_zero_when_the_clicked_item_falls_outside_k():
    rows = _rows(
        [
            (1, "A", 1, 0.1),  # clicked, but scored lowest
            (1, "B", 0, 0.9),
            (1, "C", 0, 0.8),
        ]
    )

    result = _evaluate_by_score(rows, "score", k=2, catalog_size=10)

    assert result["hit_rate_at_k"] == 0.0


def test_catalog_coverage_counts_only_the_top_k_recommended_items():
    rows = _rows(
        [
            (1, "A", 1, 0.9),
            (1, "B", 0, 0.5),
            (1, "C", 0, 0.1),  # outside top-1, must not count toward coverage
        ]
    )

    result = _evaluate_by_score(rows, "score", k=1, catalog_size=10)

    assert result["distinct_items_recommended"] == 1
    assert result["catalog_coverage_at_k"] == 0.1


def test_averages_across_multiple_impressions_independently():
    rows = _rows(
        [
            (1, "A", 1, 0.9),  # impression 1: clicked item ranked first -> hit
            (1, "B", 0, 0.1),
            (2, "C", 0, 0.9),  # impression 2: clicked item ranked last -> miss
            (2, "D", 1, 0.1),
        ]
    )

    result = _evaluate_by_score(rows, "score", k=1, catalog_size=10)

    assert result["impressions_evaluated"] == 2
    assert result["hit_rate_at_k"] == 0.5
