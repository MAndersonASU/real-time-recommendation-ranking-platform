import json
from pathlib import Path

import pandas as pd
import skops.io as sio

from recommender.evaluation.contract import TOP_K, load_catalog, load_split
from recommender.ranking.baselines import build_content_vectors
from recommender.ranking.build_dataset import VALIDATION_PATH
from recommender.ranking.train import MODEL_FEATURE_COLUMNS, MODEL_PATH
from recommender.reranking.diversity import build_diverse_slate
from recommender.reranking.freshness import (
    apply_freshness_quota,
    compute_age_days,
    compute_first_seen,
)

REPORT_PATH = Path("data/processed/mind_small/failure_analysis_report.json")

HISTORY_LENGTH_BINS = [-1, 0, 5, 20, 10_000]
HISTORY_LENGTH_LABELS = ["0", "1-5", "6-20", "20+"]


def _segment_miss_rate(frame: pd.DataFrame, mask: pd.Series) -> dict:
    subset = frame[mask]
    return {
        "n": len(subset),
        "miss_rate": float(1.0 - subset["hit"].mean()) if len(subset) else None,
    }


def analyze_failures(k: int = TOP_K) -> dict:
    """Runs the exact same reranked-slate construction the production
    evaluation already uses (recommender.evaluation.evaluate_reranking),
    but records a hit/miss flag per real impression instead of only an
    aggregate rate, tagged with three properties already computed as
    real ranking-model input features -- so a concentration of misses
    points at a specific, already-named signal the model does or
    doesn't have, not a post-hoc explanation invented after seeing the
    numbers.
    """
    train = load_split("train")
    validation_behaviors = load_split("validation")
    validation = pd.read_parquet(VALIDATION_PATH)
    news = load_catalog()

    category_by_id = news.set_index("news_id")["category"]
    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)
    first_seen = compute_first_seen(train)
    impression_time = validation_behaviors.set_index("impression_id")["time"]

    model = sio.load(MODEL_PATH)
    validation = validation.assign(
        ranked_score=model.predict_proba(validation[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    )

    records = []
    for impression_id, group in validation.groupby("impression_id", sort=False):
        clicked_rows = group[group["clicked"] == 1]
        if len(clicked_rows) == 0:
            continue

        time = impression_time.loc[impression_id]
        group = group.assign(age_days=compute_age_days(group, time, first_seen))
        diverse = build_diverse_slate(group, "ranked_score", k, category_by_id, tfidf_vectors, tfidf_row_by_id)
        reranked = apply_freshness_quota(diverse, group, "ranked_score")

        clicked_row = clicked_rows.iloc[0]
        records.append(
            {
                "impression_id": impression_id,
                "hit": bool(reranked["clicked"].sum() > 0),
                "user_history_length": int(clicked_row["user_history_length"]),
                # `popularity` is log1p(train click count) -- exactly 0.0
                # only when the clicked item was never clicked in train
                # at all (recommender.ranking.features.build_ranking_rows).
                "clicked_item_is_cold": bool(clicked_row["popularity"] == 0.0),
                "clicked_item_category_matched_history": bool(clicked_row["category_match"] == 1.0),
            }
        )

    frame = pd.DataFrame(records)
    frame["history_length_bucket"] = pd.cut(
        frame["user_history_length"], bins=HISTORY_LENGTH_BINS, labels=HISTORY_LENGTH_LABELS
    )

    by_history_length = {
        str(label): _segment_miss_rate(frame, frame["history_length_bucket"] == label)
        for label in HISTORY_LENGTH_LABELS
    }
    by_item_coldness = {
        "cold_item_never_clicked_in_train": _segment_miss_rate(frame, frame["clicked_item_is_cold"]),
        "warm_item": _segment_miss_rate(frame, ~frame["clicked_item_is_cold"]),
    }
    by_category_match = {
        "category_matched_history": _segment_miss_rate(
            frame, frame["clicked_item_category_matched_history"]
        ),
        "category_did_not_match": _segment_miss_rate(
            frame, ~frame["clicked_item_category_matched_history"]
        ),
    }

    return {
        "k": k,
        "impressions_analyzed": len(frame),
        "overall_miss_rate": float(1.0 - frame["hit"].mean()),
        "by_user_history_length": by_history_length,
        "by_clicked_item_coldness": by_item_coldness,
        "by_category_match": by_category_match,
    }


def main() -> None:
    from recommender.evaluation.publish import (
        output_dir_from_argv,
        publish_failure_analysis_report,
    )

    report = analyze_failures()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    published = publish_failure_analysis_report(
        report, output_dir=output_dir_from_argv()
    )
    print(json.dumps(report, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
