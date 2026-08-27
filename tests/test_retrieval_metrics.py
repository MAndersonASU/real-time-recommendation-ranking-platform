import math

import numpy as np
import pytest

from recommender.evaluation.metrics import ndcg_at_k, recall_at_k
from recommender.evaluation.retrieval_metrics import ndcg_at_n_known_total, recall_at_n_known_total

# Hand-worked example matching this module's own quick check: an impression
# with 3 real clicks, but retrieval's top-5 only found 1 of them, at
# position 2 (1-indexed).
RELEVANCE = np.array([0, 1, 0, 0, 0])
TRUE_CLICK_COUNT = 3
N = 5


def test_recall_at_n_known_total_uses_true_count_not_slice_count():
    recall = recall_at_n_known_total(RELEVANCE, TRUE_CLICK_COUNT, N)

    assert recall == pytest.approx(1 / 3)


def test_naive_recall_at_k_would_have_overstated_this():
    # Demonstrates the exact bug the correction exists to prevent: applied
    # naively to a top-N-only slice, the frozen recall_at_k infers "total
    # relevant" from the slice itself (1), not the true count (3).
    naive_recall = recall_at_k(RELEVANCE, N)

    assert naive_recall == pytest.approx(1.0)  # wrong: should be 1/3
    assert naive_recall != pytest.approx(1 / 3)


def test_ndcg_at_n_known_total_matches_hand_worked_value():
    # DCG@5 = 1/log2(3) (the one hit, at position 2)
    expected_dcg = 1 / math.log2(3)
    # Ideal ranking uses the TRUE click count (3, capped at N=5): [1,1,1,0,0]
    expected_idcg = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
    expected_ndcg = expected_dcg / expected_idcg

    ndcg = ndcg_at_n_known_total(RELEVANCE, TRUE_CLICK_COUNT, N)

    assert ndcg == pytest.approx(expected_ndcg)


def test_naive_ndcg_at_k_would_have_inflated_this():
    naive_ndcg = ndcg_at_k(RELEVANCE, N)
    correct_ndcg = ndcg_at_n_known_total(RELEVANCE, TRUE_CLICK_COUNT, N)

    # Naive version's "ideal" is built from the 1 visible hit only, so it
    # scores this a perfect ranking (ndcg=1.0-equivalent shape) -- inflated
    # relative to the correct answer, which accounts for the 2 missed clicks.
    assert naive_ndcg > correct_ndcg


def test_recall_and_ndcg_at_n_known_total_are_zero_with_no_true_clicks():
    assert recall_at_n_known_total(np.array([0, 0, 0]), 0, 3) == 0.0
    assert ndcg_at_n_known_total(np.array([0, 0, 0]), 0, 3) == 0.0
