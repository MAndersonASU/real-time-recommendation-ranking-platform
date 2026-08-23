import json
from pathlib import Path

import numpy as np
import pandas as pd
import skops.io as sio
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from recommender.evaluation.contract import load_catalog, load_split
from recommender.evaluation.tuning_fold import split_train_for_tuning
from recommender.ranking.baselines import compute_popularity
from recommender.ranking.build_dataset import TRAIN_PATH
from recommender.ranking.train import MODEL_FEATURE_COLUMNS
from recommender.ranking.train import MODEL_PATH as RANKING_MODEL_PATH
from recommender.reranking.freshness import (
    DEFAULT_FRESH_THRESHOLD_DAYS,
    compute_age_days,
    compute_first_seen,
)

REPORT_PATH = Path("data/processed/mind_small/tuning_decisions_verification_report.json")

# Real numbers as originally reported, measured on `validation` -- the
# leaked measurements this verification re-checks against the tune
# fold instead. Recorded here, not re-derived, so this report always
# compares against the exact historical claim (docs/ranking-model.md,
# docs/reranking-diversity.md, docs/reranking-freshness.md).
ORIGINAL_VALIDATION_POPULARITY_AUC = 0.47
ORIGINAL_VALIDATION_FOUR_PLUS_SAME_CATEGORY_RATE = 0.531
ORIGINAL_VALIDATION_SINGLE_CATEGORY_RATE = 0.046
ORIGINAL_VALIDATION_FRESH_ROW_RATE = 0.363
ORIGINAL_VALIDATION_ZERO_FRESH_IMPRESSION_RATE = 0.007


def verify_popularity_exclusion() -> dict:
    """Redoes the exact single-feature AUC check that originally
    justified dropping `popularity` from the ranking model, against a
    fold held out from train instead of against validation.

    A real, honest wrinkle found while building this check, not
    smoothed over: `popularity` is an aggregate click count computed
    over the *entire* train window (`compute_popularity`), so scoring
    it against a fold carved from train's own rows using the
    already-built `popularity` column re-creates the exact in-sample
    leakage the original exclusion decision itself named as the reason
    popularity looked artificially predictive in the first place
    (docs/ranking-model.md: "it's an aggregate click count over items
    that repeat ~272 times on average within train's own exploded
    rows, so it partly correlates with the very labels it's fit on").
    The first version of this check made exactly that mistake and
    measured AUC 0.667 -- an artifact of that leakage, not a real
    reversal of the original finding. Fixed by recomputing popularity
    from the fit half only, so the tune half's popularity values are
    genuinely out-of-sample, the same real property validation had by
    virtue of being a different day entirely.
    """
    train_rows = pd.read_parquet(TRAIN_PATH)
    fit_rows, tune_rows = split_train_for_tuning(train_rows)

    train_behaviors = load_split("train")
    fit_behaviors, _tune_behaviors = split_train_for_tuning(train_behaviors)
    popularity_fit_only = compute_popularity(fit_behaviors)

    def _out_of_sample_popularity(rows: pd.DataFrame) -> pd.Series:
        return np.log1p(rows["news_id"].map(popularity_fit_only).fillna(0.0))

    fit_popularity = _out_of_sample_popularity(fit_rows)
    tune_popularity = _out_of_sample_popularity(tune_rows)

    pipeline = Pipeline([("scale", StandardScaler()), ("logreg", LogisticRegression(max_iter=1000))])
    pipeline.fit(fit_popularity.to_numpy().reshape(-1, 1), fit_rows["clicked"].to_numpy())
    pred = pipeline.predict_proba(tune_popularity.to_numpy().reshape(-1, 1))[:, 1]
    auc = float(roc_auc_score(tune_rows["clicked"], pred))

    return {
        "original_validation_auc": ORIGINAL_VALIDATION_POPULARITY_AUC,
        "tune_fold_auc_out_of_sample_popularity": auc,
        "decision_confirmed": auc <= 0.55,  # still no better than a coin flip
        "fit_rows": len(fit_rows),
        "tune_rows": len(tune_rows),
    }


def verify_diversity_cap() -> dict:
    """Redoes the naive-top-10 category-concentration measurement that
    originally justified a category cap of 3, against the tune fold
    instead of validation. Uses the already-trained ranking model's own
    real scores (a disclosed, smaller residual overlap: that model was
    fit on all of train, including these rows, before this fold
    existed) to reproduce the same "naive top-10" population the
    original measurement scored.
    """
    train_rows = pd.read_parquet(TRAIN_PATH)
    _fit_rows, tune_rows = split_train_for_tuning(train_rows)
    news = load_catalog()
    category_by_id = news.set_index("news_id")["category"]

    ranking_model = sio.load(RANKING_MODEL_PATH)
    tune_rows = tune_rows.assign(
        ranked_score=ranking_model.predict_proba(tune_rows[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    )

    four_plus = 0
    single_category = 0
    total = 0
    for _impression_id, group in tune_rows.groupby("impression_id", sort=False):
        top10 = group.sort_values(["ranked_score", "news_id"], ascending=[False, True]).head(10)
        counts = top10["news_id"].map(category_by_id).value_counts()
        total += 1
        if len(counts) and counts.iloc[0] >= 4:
            four_plus += 1
        if len(counts) == 1:
            single_category += 1

    four_plus_rate = four_plus / total if total else None
    return {
        "original_validation_four_plus_same_category_rate": ORIGINAL_VALIDATION_FOUR_PLUS_SAME_CATEGORY_RATE,
        "tune_fold_four_plus_same_category_rate": four_plus_rate,
        "original_validation_single_category_rate": ORIGINAL_VALIDATION_SINGLE_CATEGORY_RATE,
        "tune_fold_single_category_rate": single_category / total if total else None,
        "decision_confirmed": four_plus_rate is not None and four_plus_rate >= 0.3,
        "impressions_checked": total,
    }


def verify_freshness_threshold() -> dict:
    """Redoes the freshness-candidate-coverage measurement that
    originally justified a 12-hour threshold and a minimum of 2 fresh
    items per slate, against the tune fold instead of validation.
    """
    train_behaviors = load_split("train")
    first_seen = compute_first_seen(train_behaviors)
    impression_time = train_behaviors.set_index("impression_id")["time"]

    train_rows = pd.read_parquet(TRAIN_PATH)
    _fit_rows, tune_rows = split_train_for_tuning(train_rows)

    fresh_count = 0
    total_rows = 0
    zero_fresh_impressions = 0
    total_impressions = 0
    for impression_id, group in tune_rows.groupby("impression_id", sort=False):
        if impression_id not in impression_time.index:
            continue
        time = impression_time.loc[impression_id]
        age = compute_age_days(group, time, first_seen)
        fresh = age <= DEFAULT_FRESH_THRESHOLD_DAYS
        fresh_count += int(fresh.sum())
        total_rows += len(group)
        total_impressions += 1
        if not fresh.any():
            zero_fresh_impressions += 1

    fresh_row_rate = fresh_count / total_rows if total_rows else None
    return {
        "original_validation_fresh_row_rate": ORIGINAL_VALIDATION_FRESH_ROW_RATE,
        "tune_fold_fresh_row_rate": fresh_row_rate,
        "original_validation_zero_fresh_impression_rate": ORIGINAL_VALIDATION_ZERO_FRESH_IMPRESSION_RATE,
        "tune_fold_zero_fresh_impression_rate": (
            zero_fresh_impressions / total_impressions if total_impressions else None
        ),
        "decision_confirmed": fresh_row_rate is not None and 0.2 <= fresh_row_rate <= 0.5,
        "impressions_checked": total_impressions,
    }


def main() -> None:
    report = {
        "popularity_exclusion": verify_popularity_exclusion(),
        "diversity_cap": verify_diversity_cap(),
        "freshness_threshold": verify_freshness_threshold(),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
