import json
from pathlib import Path

import numpy as np
import pandas as pd
import skops.io as sio

from recommender.evaluation.contract import TOP_K, load_catalog
from recommender.evaluation.metrics import (
    catalog_coverage,
    hit_rate_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from recommender.ranking.build_dataset import VALIDATION_PATH
from recommender.ranking.train import MODEL_FEATURE_COLUMNS, MODEL_PATH

REPORT_PATH = Path("data/processed/mind_small/ranking_evaluation_report.json")


def _evaluate_by_score(rows: pd.DataFrame, score_column: str, k: int, catalog_size: int) -> dict:
    """Orders each impression's candidates by `score_column` (descending,
    ties broken by news_id for determinism) and scores it with the same
    frozen K=10 metrics used for every Phase 2 baseline.
    """
    per_impression = {"hit_rate": [], "recall": [], "ndcg": [], "rr": []}
    recommended_items: set = set()

    for _, group in rows.groupby("impression_id", sort=False):
        ordered = group.sort_values([score_column, "news_id"], ascending=[False, True])
        relevance = ordered["clicked"].to_numpy()
        per_impression["hit_rate"].append(hit_rate_at_k(relevance, k))
        per_impression["recall"].append(recall_at_k(relevance, k))
        per_impression["ndcg"].append(ndcg_at_k(relevance, k))
        per_impression["rr"].append(reciprocal_rank(relevance))
        recommended_items.update(ordered["news_id"].iloc[:k])

    return {
        "k": k,
        "impressions_evaluated": int(rows["impression_id"].nunique()),
        "hit_rate_at_k": float(np.mean(per_impression["hit_rate"])),
        "recall_at_k": float(np.mean(per_impression["recall"])),
        "ndcg_at_k": float(np.mean(per_impression["ndcg"])),
        "mrr": float(np.mean(per_impression["rr"])),
        "catalog_coverage_at_k": catalog_coverage(recommended_items, catalog_size),
        "catalog_size": catalog_size,
        "distinct_items_recommended": len(recommended_items),
    }


def evaluate_ranking(k: int = TOP_K) -> dict:
    validation = pd.read_parquet(VALIDATION_PATH)
    catalog_size = len(load_catalog())

    model = sio.load(MODEL_PATH)
    ranked_score = model.predict_proba(validation[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    validation = validation.assign(ranked_score=ranked_score)

    return {
        "retrieval_score_only": _evaluate_by_score(validation, "retrieval_score", k, catalog_size),
        "ranked": _evaluate_by_score(validation, "ranked_score", k, catalog_size),
    }


def main() -> None:
    report = evaluate_ranking()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
