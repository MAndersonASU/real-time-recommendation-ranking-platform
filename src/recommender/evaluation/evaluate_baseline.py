import json
from pathlib import Path

import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.metrics import (
    catalog_coverage,
    hit_rate_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from recommender.ranking.baselines import compute_popularity, rank_by_popularity

SPLITS_DIR = Path("data/processed/mind_small/splits")
CATALOG_PATH = Path("data/processed/mind_small/train/news.parquet")
REPORT_PATH = Path("data/processed/mind_small/baseline_report.json")
K = 10


def evaluate_popularity_baseline(k: int = K) -> dict:
    train = pd.read_parquet(SPLITS_DIR / "train" / "behaviors.parquet")
    validation = pd.read_parquet(SPLITS_DIR / "validation" / "behaviors.parquet")
    catalog_size = len(pd.read_parquet(CATALOG_PATH))

    popularity = compute_popularity(train)
    exploded_validation = explode_impressions(validation)

    hit_rates, recalls, ndcgs, rrs = [], [], [], []
    recommended_items: set[str] = set()

    for _, group in exploded_validation.groupby("impression_id", sort=False):
        ordered = rank_by_popularity(group, popularity)
        relevance = ordered["clicked"].to_numpy()
        hit_rates.append(hit_rate_at_k(relevance, k))
        recalls.append(recall_at_k(relevance, k))
        ndcgs.append(ndcg_at_k(relevance, k))
        rrs.append(reciprocal_rank(relevance))
        recommended_items.update(ordered["news_id"].iloc[:k])

    return {
        "model": "popularity_baseline",
        "k": k,
        "impressions_evaluated": len(hit_rates),
        "hit_rate_at_k": float(np.mean(hit_rates)),
        "recall_at_k": float(np.mean(recalls)),
        "ndcg_at_k": float(np.mean(ndcgs)),
        "mrr": float(np.mean(rrs)),
        "catalog_coverage_at_k": catalog_coverage(recommended_items, catalog_size),
        "catalog_size": catalog_size,
        "distinct_items_recommended": len(recommended_items),
    }


def main() -> None:
    report = evaluate_popularity_baseline()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
