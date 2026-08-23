from unittest.mock import patch

import pandas as pd

from recommender.evaluation.evaluate_end_to_end import evaluate_end_to_end
from tests.test_pipeline import _build_context

VALIDATION_BEHAVIORS = pd.DataFrame(
    {
        "impression_id": [10, 11],
        "user_id": ["u1", "u2"],
        "time": pd.to_datetime(["2019-11-14T08:00:00", "2019-11-14T09:00:00"]),
        "history": ["n1 n2", "n4"],
        "impressions": ["n1-1 n3-0", "n5-0 n6-1"],
    }
)


def test_evaluate_end_to_end_reports_real_sampled_and_clicked_counts():
    context = _build_context()

    report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS)

    assert report["impressions_sampled"] == 2
    assert report["impressions_with_a_real_click"] == 2
    assert report["k"] == 3
    assert report["is_end_to_end_not_the_frozen_impression_list_protocol"] is True


def test_evaluate_end_to_end_metrics_are_in_a_valid_range():
    context = _build_context()

    report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS)

    assert 0.0 <= report["hit_rate_at_k"] <= 1.0
    assert 0.0 <= report["recall_at_k"] <= 1.0
    assert 0.0 <= report["ndcg_at_k"] <= 1.0
    assert 0.0 <= report["mrr"] <= 1.0


def test_evaluate_end_to_end_skips_impressions_with_no_real_click():
    context = _build_context()
    no_click_behaviors = pd.DataFrame(
        {
            "impression_id": [20],
            "user_id": ["u1"],
            "time": pd.to_datetime(["2019-11-14T08:00:00"]),
            "history": ["n1"],
            "impressions": ["n2-0 n3-0"],
        }
    )

    report = evaluate_end_to_end(context, num_impressions=1, k=3, validation=no_click_behaviors)

    assert report["impressions_with_a_real_click"] == 0
    assert report["hit_rate_at_k"] == 0.0


def test_evaluate_end_to_end_calls_the_real_pipeline_not_the_frozen_impression_list():
    """Regression test for the actual defect (audit Finding #2): the
    only ranking-evaluation code that existed before this module scored
    the ranking model against MIND's own frozen impression candidate
    list (`docs/ranking-evaluation.md`), never against what the live
    `/recommend` pipeline (Faiss retrieval -> ranking -> reranking)
    would really return for that user. Fails on a naive implementation
    that reuses the frozen impression list's own candidates (it would
    never call `safe_recommend` at all); passes only once each scored
    impression really goes through the live pipeline via a real
    `RecommendationRequest` built from that impression's own user and
    historical time.
    """
    import recommender.evaluation.evaluate_end_to_end as module

    context = _build_context()
    real_safe_recommend = module.safe_recommend
    calls = []

    def _capturing_safe_recommend(request, *args, **kwargs):
        calls.append(request)
        return real_safe_recommend(request, *args, **kwargs)

    with patch.object(module, "safe_recommend", side_effect=_capturing_safe_recommend):
        evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS)

    assert len(calls) == 2
    assert {request.user_id for request in calls} == {"u1", "u2"}
    for request, expected_time in zip(
        calls, pd.to_datetime(["2019-11-14T08:00:00", "2019-11-14T09:00:00"]), strict=True
    ):
        assert request.request_time == expected_time


def test_evaluate_end_to_end_respects_the_num_impressions_sample_size():
    context = _build_context()

    report = evaluate_end_to_end(context, num_impressions=1, k=3, validation=VALIDATION_BEHAVIORS)

    assert report["impressions_sampled"] == 1
