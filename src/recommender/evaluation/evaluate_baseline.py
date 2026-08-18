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
from recommender.ranking.baselines import (
    build_collaborative_factors,
    build_content_vectors,
    compute_popularity,
    rank_by_collaborative_filtering,
    rank_by_content_similarity,
    rank_by_popularity,
)

SPLITS_DIR = Path("data/processed/mind_small/splits")
CATALOG_PATH = Path("data/processed/mind_small/train/news.parquet")
REPORT_PATH = Path("data/processed/mind_small/baseline_report.json")
K = 10


def _aggregate(model: str, per_impression: dict, recommended_items: set, catalog_size: int) -> dict:
    return {
        "model": model,
        "k": K,
        "impressions_evaluated": len(per_impression["hit_rate"]),
        "hit_rate_at_k": float(np.mean(per_impression["hit_rate"])),
        "recall_at_k": float(np.mean(per_impression["recall"])),
        "ndcg_at_k": float(np.mean(per_impression["ndcg"])),
        "mrr": float(np.mean(per_impression["rr"])),
        "catalog_coverage_at_k": catalog_coverage(recommended_items, catalog_size),
        "catalog_size": catalog_size,
        "distinct_items_recommended": len(recommended_items),
    }


def evaluate_popularity_baseline(k: int = K) -> dict:
    train = pd.read_parquet(SPLITS_DIR / "train" / "behaviors.parquet")
    validation = pd.read_parquet(SPLITS_DIR / "validation" / "behaviors.parquet")
    catalog_size = len(pd.read_parquet(CATALOG_PATH))

    popularity = compute_popularity(train)
    exploded_validation = explode_impressions(validation)

    per_impression = {"hit_rate": [], "recall": [], "ndcg": [], "rr": []}
    recommended_items: set = set()

    for _, group in exploded_validation.groupby("impression_id", sort=False):
        ordered = rank_by_popularity(group, popularity)
        relevance = ordered["clicked"].to_numpy()
        per_impression["hit_rate"].append(hit_rate_at_k(relevance, k))
        per_impression["recall"].append(recall_at_k(relevance, k))
        per_impression["ndcg"].append(ndcg_at_k(relevance, k))
        per_impression["rr"].append(reciprocal_rank(relevance))
        recommended_items.update(ordered["news_id"].iloc[:k])

    return _aggregate("popularity_baseline", per_impression, recommended_items, catalog_size)


def evaluate_content_similarity_baseline(k: int = K) -> dict:
    train = pd.read_parquet(SPLITS_DIR / "train" / "behaviors.parquet")
    validation = pd.read_parquet(SPLITS_DIR / "validation" / "behaviors.parquet")
    news = pd.read_parquet(CATALOG_PATH)
    catalog_size = len(news)

    popularity = compute_popularity(train)
    vectors, row_by_id = build_content_vectors(news)
    history_by_impression = validation.set_index("impression_id")["history"]
    exploded_validation = explode_impressions(validation)

    per_impression = {"hit_rate": [], "recall": [], "ndcg": [], "rr": []}
    recommended_items: set = set()
    fallback_count = 0

    for impression_id, group in exploded_validation.groupby("impression_id", sort=False):
        history_raw = history_by_impression.loc[impression_id]
        history_ids = history_raw.split() if pd.notna(history_raw) else []
        if not any(nid in row_by_id for nid in history_ids):
            fallback_count += 1

        ordered = rank_by_content_similarity(group, history_ids, vectors, row_by_id, popularity)
        relevance = ordered["clicked"].to_numpy()
        per_impression["hit_rate"].append(hit_rate_at_k(relevance, k))
        per_impression["recall"].append(recall_at_k(relevance, k))
        per_impression["ndcg"].append(ndcg_at_k(relevance, k))
        per_impression["rr"].append(reciprocal_rank(relevance))
        recommended_items.update(ordered["news_id"].iloc[:k])

    report = _aggregate("content_similarity_baseline", per_impression, recommended_items, catalog_size)
    report["fallback_to_popularity_count"] = fallback_count
    return report


def evaluate_collaborative_baseline(k: int = K) -> dict:
    train = pd.read_parquet(SPLITS_DIR / "train" / "behaviors.parquet")
    validation = pd.read_parquet(SPLITS_DIR / "validation" / "behaviors.parquet")
    catalog_size = len(pd.read_parquet(CATALOG_PATH))

    popularity = compute_popularity(train)
    user_factors, item_factors, user_row_by_id, item_row_by_id = build_collaborative_factors(train)
    exploded_validation = explode_impressions(validation)

    per_impression = {"hit_rate": [], "recall": [], "ndcg": [], "rr": []}
    recommended_items: set = set()
    fallback_count = 0

    for (impression_id, user_id), group in exploded_validation.groupby(
        ["impression_id", "user_id"], sort=False
    ):
        if user_id not in user_row_by_id:
            fallback_count += 1

        ordered = rank_by_collaborative_filtering(
            group, user_id, user_factors, item_factors, user_row_by_id, item_row_by_id, popularity
        )
        relevance = ordered["clicked"].to_numpy()
        per_impression["hit_rate"].append(hit_rate_at_k(relevance, k))
        per_impression["recall"].append(recall_at_k(relevance, k))
        per_impression["ndcg"].append(ndcg_at_k(relevance, k))
        per_impression["rr"].append(reciprocal_rank(relevance))
        recommended_items.update(ordered["news_id"].iloc[:k])

    report = _aggregate("collaborative_baseline", per_impression, recommended_items, catalog_size)
    report["fallback_to_popularity_count"] = fallback_count
    return report


def main() -> None:
    report = {
        "popularity": evaluate_popularity_baseline(),
        "content_similarity": evaluate_content_similarity_baseline(),
        "collaborative": evaluate_collaborative_baseline(),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
