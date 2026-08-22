import pytest

from recommender.tracking.experiment_log import log_run
from recommender.tracking.stage_comparison import STAGE_ORDER, compare_stages


def _log_all_stages(path, overrides=None):
    overrides = overrides or {}
    base_metrics = {
        "baseline_content_similarity_k10": {"metric_hit_rate_at_k": 0.60, "metric_recall_at_k": 0.55, "metric_ndcg_at_k": 0.30},
        "retrieval_score_as_sort_key_k10": {"metric_hit_rate_at_k": 0.62, "metric_recall_at_k": 0.57, "metric_ndcg_at_k": 0.32},
        "ranking_model_k10": {"metric_hit_rate_at_k": 0.68, "metric_recall_at_k": 0.60, "metric_ndcg_at_k": 0.37},
        "reranking_diverse_fresh_k10": {"metric_hit_rate_at_k": 0.67, "metric_recall_at_k": 0.585, "metric_ndcg_at_k": 0.362},
    }
    for run_name in STAGE_ORDER:
        metrics = overrides.get(run_name, base_metrics[run_name])
        log_run(
            run_name,
            params={"k": 10},
            metrics={k.removeprefix("metric_"): v for k, v in metrics.items()},
            path=path,
        )


def test_compare_stages_orders_rows_as_baseline_to_reranking(tmp_path):
    path = tmp_path / "log.jsonl"
    _log_all_stages(path)

    comparison = compare_stages(path=path)

    assert list(comparison["run_name"]) == STAGE_ORDER
    assert list(comparison["stage"]) == [
        "Best baseline (content similarity)", "Retrieval", "Ranking", "Reranking",
    ]


def test_compare_stages_computes_deltas_between_adjacent_stages(tmp_path):
    path = tmp_path / "log.jsonl"
    _log_all_stages(path)

    comparison = compare_stages(path=path)

    assert comparison["metric_hit_rate_at_k_delta"].iloc[0] != comparison["metric_hit_rate_at_k_delta"].iloc[0]  # NaN for the first row
    assert comparison["metric_hit_rate_at_k_delta"].iloc[1] == pytest.approx(0.02)
    assert comparison["metric_hit_rate_at_k_delta"].iloc[2] == pytest.approx(0.06)
    assert comparison["metric_hit_rate_at_k_delta"].iloc[3] == pytest.approx(-0.01)


def test_compare_stages_raises_clearly_when_a_stage_was_never_logged(tmp_path):
    path = tmp_path / "log.jsonl"
    log_run("baseline_content_similarity_k10", params={"k": 10}, metrics={"hit_rate_at_k": 0.6}, path=path)

    with pytest.raises(ValueError, match="missing logged runs"):
        compare_stages(path=path)
