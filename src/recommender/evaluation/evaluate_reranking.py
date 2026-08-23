import json
from pathlib import Path

import numpy as np
import pandas as pd
import skops.io as sio

from recommender.evaluation.contract import TOP_K, load_catalog, load_split
from recommender.evaluation.metrics import catalog_coverage, hit_rate_at_k, reciprocal_rank
from recommender.evaluation.retrieval_metrics import ndcg_at_n_known_total, recall_at_n_known_total
from recommender.ranking.baselines import build_content_vectors
from recommender.ranking.build_dataset import VALIDATION_PATH
from recommender.ranking.train import MODEL_FEATURE_COLUMNS, MODEL_PATH
from recommender.reranking.diversity import build_diverse_slate
from recommender.reranking.freshness import (
    DEFAULT_FRESH_THRESHOLD_DAYS,
    DEFAULT_MIN_FRESH_IN_SLATE,
    apply_freshness_quota,
    compute_age_days,
    compute_first_seen,
)

REPORT_PATH = Path("data/processed/mind_small/reranking_evaluation_report.json")


def _relevance_metrics(ordered: pd.DataFrame, k: int, true_relevant_count: int) -> dict:
    """`ordered` is only a k-item slate, not the impression's complete
    candidate set (both the plain ranked slate and the reranked one
    discard everything outside the top k) -- the same situation Step
    3.5's retrieval evaluation hit, and the same fix: recall/NDCG take
    the true relevant count as an explicit argument instead of inferring
    it from the slate itself, which would silently ignore a real click
    that fell outside the slate.
    """
    relevance = ordered["clicked"].to_numpy()
    return {
        "hit_rate": hit_rate_at_k(relevance, k),
        "recall": recall_at_n_known_total(relevance, true_relevant_count, k),
        "ndcg": ndcg_at_n_known_total(relevance, true_relevant_count, k),
        "rr": reciprocal_rank(relevance),
    }


def _diversity_metrics(ordered: pd.DataFrame, category_by_id: pd.Series) -> dict:
    counts = ordered["news_id"].map(category_by_id).value_counts()
    return {
        "distinct_categories": len(counts),
        "max_category_count": int(counts.iloc[0]) if len(counts) else 0,
    }


def _freshness_metrics(
    ordered: pd.DataFrame, fresh_threshold_days: float, min_fresh_in_slate: int
) -> dict:
    if len(ordered) == 0:
        return {"mean_age_days": float("nan"), "fresh_fraction": 0.0, "below_fresh_quota": True}
    fresh_count = int((ordered["age_days"] <= fresh_threshold_days).sum())
    return {
        "mean_age_days": float(ordered["age_days"].mean()),
        "fresh_fraction": float(fresh_count / len(ordered)),
        # The quota's actual, guaranteed effect shows up here, not in the
        # population mean above -- a floor enforced on already-compliant
        # slates barely moves an aggregate average.
        "below_fresh_quota": fresh_count < min_fresh_in_slate,
    }


def _accumulate(store: dict, values: dict) -> None:
    for key, value in values.items():
        store.setdefault(key, []).append(value)


def _summarize(relevance: dict, diversity: dict, freshness: dict, recommended: set, catalog_size: int) -> dict:
    return {
        "hit_rate_at_k": float(np.mean(relevance["hit_rate"])),
        "recall_at_k": float(np.mean(relevance["recall"])),
        "ndcg_at_k": float(np.mean(relevance["ndcg"])),
        "mrr": float(np.mean(relevance["rr"])),
        "catalog_coverage_at_k": catalog_coverage(recommended, catalog_size),
        "distinct_items_recommended": len(recommended),
        "mean_distinct_categories": float(np.mean(diversity["distinct_categories"])),
        "mean_max_category_count": float(np.mean(diversity["max_category_count"])),
        "mean_age_days": float(np.nanmean(freshness["mean_age_days"])),
        "mean_fresh_fraction": float(np.mean(freshness["fresh_fraction"])),
        "fraction_of_slates_below_fresh_quota": float(np.mean(freshness["below_fresh_quota"])),
    }


def evaluate_reranking(k: int = TOP_K) -> dict:
    train = load_split("train")
    validation_behaviors = load_split("validation")
    validation = pd.read_parquet(VALIDATION_PATH)
    news = load_catalog()
    catalog_size = len(news)

    category_by_id = news.set_index("news_id")["category"]
    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)
    first_seen = compute_first_seen(train)
    impression_time = validation_behaviors.set_index("impression_id")["time"]

    model = sio.load(MODEL_PATH)
    validation = validation.assign(
        ranked_score=model.predict_proba(validation[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    )

    baseline_relevance: dict = {}
    reranked_relevance: dict = {}
    baseline_diversity: dict = {}
    reranked_diversity: dict = {}
    baseline_freshness: dict = {}
    reranked_freshness: dict = {}
    baseline_recommended: set = set()
    reranked_recommended: set = set()

    for impression_id, group in validation.groupby("impression_id", sort=False):
        time = impression_time.loc[impression_id]
        group = group.assign(age_days=compute_age_days(group, time, first_seen))
        true_relevant_count = int(group["clicked"].sum())

        baseline_top = group.sort_values(["ranked_score", "news_id"], ascending=[False, True]).head(k)

        diverse = build_diverse_slate(
            group,
            score_column="ranked_score",
            k=k,
            category_by_id=category_by_id,
            tfidf_vectors=tfidf_vectors,
            tfidf_row_by_id=tfidf_row_by_id,
        )
        reranked = apply_freshness_quota(diverse, group, score_column="ranked_score")

        _accumulate(baseline_relevance, _relevance_metrics(baseline_top, k, true_relevant_count))
        _accumulate(reranked_relevance, _relevance_metrics(reranked, k, true_relevant_count))
        _accumulate(baseline_diversity, _diversity_metrics(baseline_top, category_by_id))
        _accumulate(reranked_diversity, _diversity_metrics(reranked, category_by_id))
        _accumulate(
            baseline_freshness,
            _freshness_metrics(baseline_top, DEFAULT_FRESH_THRESHOLD_DAYS, DEFAULT_MIN_FRESH_IN_SLATE),
        )
        _accumulate(
            reranked_freshness,
            _freshness_metrics(reranked, DEFAULT_FRESH_THRESHOLD_DAYS, DEFAULT_MIN_FRESH_IN_SLATE),
        )

        baseline_recommended.update(baseline_top["news_id"])
        reranked_recommended.update(reranked["news_id"])

    return {
        "k": k,
        "impressions_evaluated": int(validation["impression_id"].nunique()),
        "ranked_only": _summarize(
            baseline_relevance, baseline_diversity, baseline_freshness, baseline_recommended, catalog_size
        ),
        "reranked": _summarize(
            reranked_relevance, reranked_diversity, reranked_freshness, reranked_recommended, catalog_size
        ),
    }


def main() -> None:
    report = evaluate_reranking()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
