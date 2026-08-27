from pathlib import Path

import pandas as pd

from recommender.tracking.experiment_log import DEFAULT_LOG_PATH, load_runs

METRIC_COLUMNS = ["metric_hit_rate_at_k", "metric_recall_at_k", "metric_ndcg_at_k"]

# The strongest of Phase 2's three non-learned baselines (content
# similarity beat popularity and collaborative filtering on every
# metric), not the weakest one -- comparing the pipeline's cumulative
# gain against the weakest baseline would overstate how much retrieval,
# ranking, and reranking actually add on top of the best pre-existing
# approach.
STAGE_ORDER = [
    "baseline_content_similarity_k10",
    "retrieval_score_as_sort_key_k10",
    "ranking_model_k10",
    "reranking_diverse_fresh_k10",
]
STAGE_LABELS = ["Best baseline (content similarity)", "Retrieval", "Ranking", "Reranking"]


def compare_stages(path: Path = DEFAULT_LOG_PATH) -> pd.DataFrame:
    """Orders the tracked runs into the pipeline's real stage progression
    and computes each metric's change from the stage immediately before
    it -- every stage compared here was evaluated on the same K=10,
    same 30,270-impression validation split (docs/experiments/evaluation-protocol.md,
    frozen since Phase 2), so a delta between adjacent rows reflects that
    one added stage, not a different evaluation population.
    """
    runs = load_runs(path=path).set_index("run_name")
    missing = [name for name in STAGE_ORDER if name not in runs.index]
    if missing:
        raise ValueError(f"stage comparison is missing logged runs: {missing}")

    stages = runs.loc[STAGE_ORDER, METRIC_COLUMNS].copy()
    stages.insert(0, "stage", STAGE_LABELS)
    for column in METRIC_COLUMNS:
        stages[f"{column}_delta"] = stages[column].diff()
    return stages.reset_index()
