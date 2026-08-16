import math

import numpy as np
import pytest

from recommender.evaluation.metrics import (
    catalog_coverage,
    dcg_at_k,
    hit_rate_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

# Hand-worked example: a ranked list of 5 items, clicked items marked 1.
# Clicks landed at positions 2 and 5 (1-indexed): [0, 1, 0, 0, 1]
RELEVANCE = np.array([0, 1, 0, 0, 1])


def test_hit_rate_at_k():
    assert hit_rate_at_k(RELEVANCE, k=1) == 0.0  # top1 = [0], no hit
    assert hit_rate_at_k(RELEVANCE, k=3) == 1.0  # top3 = [0, 1, 0], hit at rank 2


def test_recall_at_k():
    assert recall_at_k(RELEVANCE, k=3) == pytest.approx(0.5)  # 1 of 2 clicks in top 3
    assert recall_at_k(RELEVANCE, k=5) == pytest.approx(1.0)  # both clicks captured


def test_recall_at_k_with_no_relevant_items_is_zero():
    assert recall_at_k(np.array([0, 0, 0]), k=3) == 0.0


def test_reciprocal_rank():
    # first click at rank 2 (1-indexed) -> 1/2
    assert reciprocal_rank(RELEVANCE) == pytest.approx(0.5)
    assert reciprocal_rank(np.array([0, 0, 0])) == 0.0


def test_dcg_and_ndcg_hand_worked():
    # DCG@3: top3 = [0, 1, 0] -> 0/log2(2) + 1/log2(3) + 0/log2(4)
    expected_dcg3 = 1 / math.log2(3)
    assert dcg_at_k(RELEVANCE, k=3) == pytest.approx(expected_dcg3)

    # Ideal ordering sorts relevance descending: [1, 1, 0, 0, 0], top3 = [1, 1, 0]
    # IDCG@3 = 1/log2(2) + 1/log2(3) + 0/log2(4) = 1 + 1/log2(3)
    expected_idcg3 = 1 + 1 / math.log2(3)
    expected_ndcg3 = expected_dcg3 / expected_idcg3
    assert ndcg_at_k(RELEVANCE, k=3) == pytest.approx(expected_ndcg3)


def test_ndcg_is_one_for_a_perfect_ranking():
    perfect = np.array([1, 1, 0, 0])
    assert ndcg_at_k(perfect, k=4) == pytest.approx(1.0)


def test_ndcg_with_no_relevant_items_is_zero():
    assert ndcg_at_k(np.array([0, 0, 0]), k=3) == 0.0


def test_catalog_coverage():
    assert catalog_coverage({"N1", "N2"}, catalog_size=10) == pytest.approx(0.2)
    assert catalog_coverage(set(), catalog_size=0) == 0.0
