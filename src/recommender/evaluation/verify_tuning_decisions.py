import json
from functools import lru_cache

import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from recommender.evaluation.contract import TOP_K, load_catalog, load_split
from recommender.evaluation.sampling import (
    DEFAULT_SAMPLE_SEED,
    describe_sample,
    sample_impression_ids,
)
from recommender.evaluation.tuning_fold import (
    chronological_tuning_split_impression_ids,
    split_rows_by_impression_ids,
    split_train_for_tuning,
)
from recommender.paths import mind_small_path
from recommender.ranking.baselines import build_content_vectors, compute_popularity
from recommender.ranking.build_dataset import TRAIN_PATH
from recommender.ranking.features import history_ids_from_raw
from recommender.ranking.train import MODEL_FEATURE_COLUMNS, train_ranking_model
from recommender.reranking.diversity import DEFAULT_MAX_PER_CATEGORY, build_diverse_slate
from recommender.reranking.freshness import (
    DEFAULT_FRESH_THRESHOLD_DAYS,
    DEFAULT_MIN_FRESH_IN_SLATE,
    apply_freshness_quota,
    compute_age_days,
    compute_first_seen,
)
from recommender.serving.pipeline import MIN_RETRIEVAL_CANDIDATES, RETRIEVAL_MULTIPLIER

# A real, bounded sample of tune-fold impressions for the alternative-
# value comparisons below (diversity cap values, freshness thresholds):
# `build_diverse_slate`'s near-duplicate check is real per-impression
# work, and running it across every one of ~25,000 tune-fold impressions
# for each of several candidate values would make this check too slow
# to actually run as part of routine verification. A real, disclosed
# sampling tradeoff, not a hidden one -- the sample size is reported in
# every comparison's own output.
COMPARISON_SAMPLE_IMPRESSIONS = 1500

REPORT_PATH = mind_small_path("tuning_decisions_verification_report.json")

# Real numbers as originally reported, measured on `validation` -- the
# leaked measurements this verification re-checks against the tune
# fold instead. Recorded here, not re-derived, so this report always
# compares against the exact historical claim (docs/experiments/ranking-model.md,
# docs/experiments/reranking-diversity.md, docs/experiments/reranking-freshness.md).
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
    (docs/experiments/ranking-model.md: "it's an aggregate click count over items
    that repeat ~272 times on average within train's own exploded
    rows, so it partly correlates with the very labels it's fit on").
    The first version of this check made exactly that mistake and
    measured AUC 0.667 -- an artifact of that leakage, not a real
    reversal of the original finding. Fixed by recomputing popularity
    from the fit half only, so the tune half's popularity values are
    genuinely out-of-sample, the same real property validation had by
    virtue of being a different day entirely.
    """
    train_rows, feature_provenance = _load_tuning_rows()
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
        "feature_provenance": feature_provenance,
        "original_validation_auc": ORIGINAL_VALIDATION_POPULARITY_AUC,
        "tune_fold_auc_out_of_sample_popularity": auc,
        "decision_confirmed": auc <= 0.55,  # still no better than a coin flip
        "fit_rows": len(fit_rows),
        "tune_rows": len(tune_rows),
    }


def verify_popularity_exclusion_with_temporal_split() -> dict:
    """Directly tests the one real, unresolved open question left by
    `verify_popularity_exclusion` (`docs/experiments/evaluation-integrity.md`): does
    a *random* split of train's own rows let short-term popularity
    recency leak across the fit/tune boundary in a way the real
    `validation` split (a separate, later day) never could?

    Identical to `verify_popularity_exclusion` in every respect except
    one: `fit`/`tune` are carved by real chronological order
    (`chronological_tuning_split_impression_ids`) instead of randomly by
    impression_id. If recency leakage explains the discrepancy (0.665 on
    the random split vs. 0.47 on validation), this chronological split
    -- which gives `tune` the same kind of real temporal gap from `fit`
    that `validation` has from `train` -- should bring the AUC back down
    toward the original 0.47. If it doesn't, that's real evidence the
    discrepancy is not simply a recency-leakage artifact, and the
    original exclusion decision would need real reconsideration (a
    separate, larger decision requiring model retraining, not made
    here).
    """
    train_rows, feature_provenance = _load_tuning_rows()
    train_behaviors = load_split("train")
    fit_impression_ids, tune_impression_ids = chronological_tuning_split_impression_ids(train_behaviors)

    fit_rows, tune_rows = split_rows_by_impression_ids(train_rows, fit_impression_ids, tune_impression_ids)
    fit_behaviors, _tune_behaviors = split_rows_by_impression_ids(
        train_behaviors, fit_impression_ids, tune_impression_ids
    )
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
        "feature_provenance": feature_provenance,
        "original_validation_auc": ORIGINAL_VALIDATION_POPULARITY_AUC,
        "chronological_split_tune_fold_auc": auc,
        "recency_leakage_explanation_supported": auc <= 0.55,
        "fit_rows": len(fit_rows),
        "tune_rows": len(tune_rows),
    }



@lru_cache(maxsize=1)
def _impression_metadata() -> pd.DataFrame | None:
    """impression_id -> user_id, time, from the training behaviours.

    The ranking feature table is one row per candidate and carries
    neither column, so a sample described from it alone could report how
    many impressions were drawn but not how many *users* they came from
    or what stretch of time they covered -- the two facts that say
    whether a sample is representative at all. Cached because every
    comparison would otherwise re-read the same split.

    Returns None when the licensed split is not present. Describing a
    sample is reporting, not measurement, and it must not be the thing
    that makes a comparison require the dataset: an earlier version
    loaded the split unconditionally and broke three tests that had
    always run on synthetic in-memory frames.
    """
    try:
        behaviors = load_split("train")
    except (FileNotFoundError, OSError):
        return None
    return behaviors[["impression_id", "user_id", "time"]].drop_duplicates("impression_id")


def _describe_tuning_sample(frame: pd.DataFrame, selected, seed: int) -> dict:
    """`describe_sample` with user and time metadata joined back on where
    it is available.

    When the split is absent the description still reports population,
    count, fraction and selection digest, and says explicitly that the
    user and time facts are missing -- an absent field would otherwise
    read as "not applicable" rather than "not looked up".
    """
    metadata = _impression_metadata()
    if metadata is None:
        description = describe_sample(frame, selected, seed=seed)
        description["user_and_time_metadata"] = (
            "unavailable -- the behaviours split was not present when this sample "
            "was described"
        )
        return description

    ids = pd.DataFrame({"impression_id": frame["impression_id"].drop_duplicates()})
    enriched = ids.merge(metadata, on="impression_id", how="left")
    return describe_sample(enriched, selected, seed=seed)


def collect_sampling(report: dict) -> dict:
    """Gathers every comparison's own sampling description.

    Each comparison draws its own sample, so there is no single one to
    report. Walking for them rather than reaching into a fixed key path
    is deliberate: an earlier version indexed
    `report["diversity_cap"]["sampling"]`, which sits one level above
    where the description actually is, and the mistake only surfaced as
    a KeyError after a twenty-minute run had already finished
    measuring. A publishing step must not be able to discard completed
    work over a key path.
    """
    found: dict = {}

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "sampling" and isinstance(value, dict):
                found[path.lstrip(".")] = value
            elif isinstance(value, dict):
                walk(value, f"{path}.{key}")

    walk(report, "")
    # Grouped by selection digest, not reduced to one flag. An earlier
    # version asked "do all comparisons share a sample?", which answered
    # False as soon as a third comparison with a different eligible
    # population was added -- and then described every sample as
    # independent, while two of the three were provably identical. Which
    # comparisons share which sample is the fact a reader needs, so it is
    # reported directly.
    groups: dict[str, list[str]] = {}
    for name, description in found.items():
        groups.setdefault(description.get("selected_ids_sha256", "unknown"), []).append(name)
    shared_groups = {
        digest: sorted(names) for digest, names in groups.items() if len(names) > 1
    }

    return {
        "method": "seeded uniform random without replacement",
        "shared_samples": shared_groups,
        "sharing_note": (
            "Comparisons listed together under one digest were run on the identical "
            "set of impressions. That is deliberate: comparing reranking parameters "
            "on the same impressions is a paired comparison and removes between-"
            "sample variation from the difference being measured. Comparisons with "
            "different digests draw from different eligible populations. An earlier "
            "version of this field claimed every sample was drawn independently, "
            "which was not true of any two of them."
            if shared_groups
            else "No two comparisons drew the same sample."
        ),
        "seed": DEFAULT_SAMPLE_SEED,
        "by_comparison": found,
    }


def _load_tuning_rows() -> tuple[pd.DataFrame, dict]:
    """Loads the feature table the tuning comparisons run on.

    Prefers the fit-half table (`recommender.ranking.build_dataset_fit_only`),
    whose `retrieval_score` and fitted context were both produced without
    any tune-fold information. The deployed table is the fallback, and it
    is a compromised one: its retrieval model was trained on the tuning
    fold, so a comparison run against it is development evidence with
    residual feature leakage, not a held-out result.

    Which table was used is returned rather than inferred, and travels
    into the published report -- a leaked run and a clean one must not
    look the same afterwards.
    """
    from recommender.ranking.build_dataset_fit_only import FIT_ONLY_TRAIN_PATH

    if FIT_ONLY_TRAIN_PATH.exists():
        return pd.read_parquet(FIT_ONLY_TRAIN_PATH), {
            "feature_table": "fit_half_only",
            "retrieval_model_trained_on": "fit half only",
            "feature_context_fitted_on": "fit half only",
            "tune_fold_leakage": False,
        }
    return pd.read_parquet(TRAIN_PATH), {
        "feature_table": "full_train",
        "retrieval_model_trained_on": "all of train, including the tuning fold",
        "feature_context_fitted_on": "all of train, including the tuning fold",
        "tune_fold_leakage": True,
        "note": (
            "residual feature leakage: run "
            "`python -m recommender.retrieval.train_fit_only` then "
            "`python -m recommender.ranking.build_dataset_fit_only` to remove it"
        ),
    }


def _score_with_held_out_model(tune_rows: pd.DataFrame, fit_rows: pd.DataFrame) -> pd.DataFrame:
    """Scores tune-fold rows with a model fitted on the fit half only.

    Reusing the production model would score these rows with a model
    that had already seen them, which is not the held-out check it
    would appear to be.
    """
    model = train_ranking_model(fit_rows)
    return tune_rows.assign(
        ranked_score=model.predict_proba(tune_rows[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    )


def _compare_diversity_cap_values(
    scored_rows: pd.DataFrame,
    category_by_id: pd.Series,
    sample_impressions: int = COMPARISON_SAMPLE_IMPRESSIONS,
    news: pd.DataFrame | None = None,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
) -> dict:
    """Runs the real diversity-reranking algorithm at several candidate
    cap values -- not just the currently-configured one's own behavior
    -- and reports each value's real relevance/diversity tradeoff.
    Predefined selection rule, decided before looking at the numbers
    this produces: choose the smallest cap value whose mean distinct
    categories per slate reaches at least 90% of the uncapped value's
    own mean -- below that bar, a smaller cap is giving up relevance for
    a diversity gain judged not worth it; the smallest cap clearing the
    bar is preferred to avoid giving up more relevance than needed.
    """
    # Injectable so a unit test can exercise the real comparison logic
    # on synthetic articles. Loading the catalog unconditionally made
    # this function require the licensed dataset even when every other
    # input was supplied by the caller.
    news = news if news is not None else load_catalog()
    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)

    selected = sample_impression_ids(scored_rows, sample_impressions, seed=sample_seed)
    sample = scored_rows[scored_rows["impression_id"].isin(selected)]

    candidate_caps = [1, 2, 3, 5, None]  # None stands in for "no cap at all"
    by_cap: dict[str, dict] = {}
    for cap in candidate_caps:
        effective_cap = cap if cap is not None else len(news)  # effectively unconstrained
        total_relevance = 0.0
        total_distinct_categories = 0
        n = 0
        for _impression_id, group in sample.groupby("impression_id", sort=False):
            slate = build_diverse_slate(
                group, "ranked_score", 10, category_by_id, tfidf_vectors, tfidf_row_by_id,
                max_per_category=effective_cap,
            )
            total_relevance += float(slate["ranked_score"].sum())
            total_distinct_categories += int(slate["news_id"].map(category_by_id).nunique())
            n += 1
        by_cap[str(cap) if cap is not None else "no_cap"] = {
            "mean_slate_relevance": total_relevance / n if n else None,
            "mean_distinct_categories": total_distinct_categories / n if n else None,
        }

    no_cap_relevance = by_cap["no_cap"]["mean_slate_relevance"]

    # A relevance-budget rule, replacing an earlier one that could not
    # work: because slate diversity rises monotonically as the cap
    # falls, any bar stated relative to the *uncapped* (least diverse)
    # case is cleared by every capped value, so that rule always
    # selected the smallest cap tried regardless of what it cost.
    #
    # This rule instead bounds the cost and maximizes the benefit: among
    # caps that keep mean slate relevance within `budget` of the
    # uncapped mean, take the one with the highest mean distinct
    # category count. Nothing is monotone-trivial about it -- an
    # aggressive cap buys diversity but spends relevance, so it can and
    # does fall outside a tight budget.
    def _select_under_budget(budget: float):
        floor = budget * no_cap_relevance if no_cap_relevance else None
        if floor is None:
            return None
        affordable = [
            cap for cap in (1, 2, 3, 5)
            if (by_cap[str(cap)]["mean_slate_relevance"] or 0.0) >= floor
        ]
        if not affordable:
            return None
        return max(affordable, key=lambda cap: by_cap[str(cap)]["mean_distinct_categories"])

    # Reported across several budgets rather than one. The budget is a
    # product decision about how much relevance a diversity gain is
    # worth -- it is not something this data can settle, and fixing a
    # single value after seeing the table above would be exactly the
    # post-hoc rule-fitting this whole document exists to avoid. The
    # honest output is how the choice moves as the budget moves.
    by_budget = {f"{budget:.2f}": _select_under_budget(budget) for budget in (0.85, 0.90, 0.95, 0.99)}

    return {
        "sample_impressions": len(selected),
        "sampling": _describe_tuning_sample(scored_rows, selected, seed=sample_seed),
        "by_cap_value": by_cap,
        "selection_rule": (
            "highest mean distinct-category count among caps whose mean slate relevance "
            "stays within a given budget of the uncapped mean"
        ),
        "cap_selected_by_relevance_budget": by_budget,
        "currently_configured_cap": DEFAULT_MAX_PER_CATEGORY,
        "budgets_supporting_current_configuration": [
            budget for budget, cap in by_budget.items() if cap == DEFAULT_MAX_PER_CATEGORY
        ],
    }


def verify_diversity_cap() -> dict:
    """Redoes the naive-top-10 category-concentration measurement that
    originally justified a category cap of 3, against the tune fold
    instead of validation, and separately compares the real diversity
    algorithm's own output across alternative cap values -- not only
    the currently-configured value's own behavior.

    Fits a fresh ranking model on the fit half only, rather than
    reusing the already-trained production model (which was fit on
    *all* of train, including these same tuning rows) -- scores from a
    model that had already seen the tune fold's own labels would not be
    a genuinely held-out check.
    """
    train_rows, feature_provenance = _load_tuning_rows()
    fit_rows, tune_rows = split_train_for_tuning(train_rows)
    news = load_catalog()
    category_by_id = news.set_index("news_id")["category"]

    held_out_ranking_model = train_ranking_model(fit_rows)
    tune_rows = tune_rows.assign(
        ranked_score=held_out_ranking_model.predict_proba(tune_rows[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
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
        "feature_provenance": feature_provenance,
        "original_validation_four_plus_same_category_rate": ORIGINAL_VALIDATION_FOUR_PLUS_SAME_CATEGORY_RATE,
        "tune_fold_four_plus_same_category_rate": four_plus_rate,
        "original_validation_single_category_rate": ORIGINAL_VALIDATION_SINGLE_CATEGORY_RATE,
        "tune_fold_single_category_rate": single_category / total if total else None,
        "decision_confirmed": four_plus_rate is not None and four_plus_rate >= 0.3,
        "impressions_checked": total,
        "ranking_model_excludes_tuning_rows": True,
        "cap_value_comparison": _compare_diversity_cap_values(tune_rows, category_by_id),
    }


def _coverage_at_threshold(
    tune_rows: pd.DataFrame, impression_time: pd.Series, first_seen: pd.Series, threshold_days: float
) -> dict:
    fresh_count = 0
    total_rows = 0
    zero_fresh_impressions = 0
    total_impressions = 0
    for impression_id, group in tune_rows.groupby("impression_id", sort=False):
        if impression_id not in impression_time.index:
            continue
        time = impression_time.loc[impression_id]
        age = compute_age_days(group, time, first_seen)
        fresh = age <= threshold_days
        fresh_count += int(fresh.sum())
        total_rows += len(group)
        total_impressions += 1
        if not fresh.any():
            zero_fresh_impressions += 1
    return {
        "fresh_row_rate": fresh_count / total_rows if total_rows else None,
        "zero_fresh_impression_rate": (
            zero_fresh_impressions / total_impressions if total_impressions else None
        ),
        "impressions_checked": total_impressions,
    }


def _compare_freshness_threshold_values(
    tune_rows: pd.DataFrame, impression_time: pd.Series, first_seen: pd.Series
) -> dict:
    """Compares real coverage at several candidate thresholds -- not
    only the currently-configured 12-hour (0.5-day) value's own
    behavior. Predefined selection rule, decided before looking at the
    numbers this produces: the original threshold was chosen so a
    freshness quota is "almost always satisfiable, scarce enough to
    mean something" (docs/experiments/reranking-freshness.md) -- operationalized
    here as choosing the smallest threshold whose zero-fresh-impression
    rate stays under 5% (the quota fails outright for less than 1 in 20
    impressions), preferring the smallest such threshold since a
    smaller threshold means a stricter, more meaningful notion of
    "fresh."
    """
    candidate_thresholds_days = [0.25, 0.5, 1.0, 2.0, 7.0]
    by_threshold = {
        str(threshold): _coverage_at_threshold(tune_rows, impression_time, first_seen, threshold)
        for threshold in candidate_thresholds_days
    }

    selected_threshold = None
    for threshold in candidate_thresholds_days:
        zero_rate = by_threshold[str(threshold)]["zero_fresh_impression_rate"]
        if zero_rate is not None and zero_rate < 0.05:
            selected_threshold = threshold
            break

    return {
        "by_threshold_days": by_threshold,
        "selection_rule": "smallest threshold with a zero-fresh-impression rate under 5%",
        "threshold_selected_by_rule": selected_threshold,
        "currently_configured_threshold_days": DEFAULT_FRESH_THRESHOLD_DAYS,
        "rule_supports_current_configuration": selected_threshold == DEFAULT_FRESH_THRESHOLD_DAYS,
    }


MIN_FRESH_CANDIDATE_VALUES = (0, 1, 2, 3, 5)


def _compare_min_fresh_values(
    scored_rows: pd.DataFrame,
    category_by_id: pd.Series,
    first_seen: pd.Series,
    impression_time: pd.Series,
    news: pd.DataFrame | None = None,
    sample_impressions: int = COMPARISON_SAMPLE_IMPRESSIONS,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
) -> dict:
    """Compares real alternatives for the minimum-fresh-items quota,
    the one reranking parameter never previously checked against
    anything but itself.

    Rule, stated before the numbers below were produced: take the
    largest quota whose mean slate relevance stays within a stated
    budget of the unconstrained (quota 0) slate.

    Bounding the *cost* rather than the benefit, deliberately. Fresh
    items delivered rises monotonically with the quota, so any rule
    phrased in freshness terms would be cleared by every candidate and
    would collapse into "pick the largest value tried" -- the defect
    that made the first diversity-cap rule meaningless
    (docs/experiments/evaluation-integrity.md). Relevance is what a quota actually
    spends, so that is what the rule constrains.
    """
    news = news if news is not None else load_catalog()
    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)

    selected = sample_impression_ids(scored_rows, sample_impressions, seed=sample_seed)
    sample = scored_rows[scored_rows["impression_id"].isin(selected)]

    by_value: dict[str, dict] = {}
    for min_fresh in MIN_FRESH_CANDIDATE_VALUES:
        total_relevance = 0.0
        total_fresh = 0
        quota_met = 0
        n = 0
        for impression_id, group in sample.groupby("impression_id", sort=False):
            if impression_id not in impression_time.index:
                continue
            aged = group.assign(
                age_days=compute_age_days(
                    group, pd.Timestamp(impression_time.loc[impression_id]), first_seen
                )
            )
            slate = build_diverse_slate(
                aged, "ranked_score", TOP_K, category_by_id, tfidf_vectors, tfidf_row_by_id
            )
            if min_fresh > 0:
                slate = apply_freshness_quota(
                    slate, aged, "ranked_score", min_fresh_in_slate=min_fresh
                )
            fresh_count = int((slate["age_days"] <= DEFAULT_FRESH_THRESHOLD_DAYS).sum())
            total_relevance += float(slate["ranked_score"].sum())
            total_fresh += fresh_count
            quota_met += int(fresh_count >= min_fresh)
            n += 1
        by_value[str(min_fresh)] = {
            "mean_slate_relevance": total_relevance / n if n else None,
            "mean_fresh_items_in_slate": total_fresh / n if n else None,
            "share_of_slates_meeting_quota": quota_met / n if n else None,
        }

    unconstrained = by_value["0"]["mean_slate_relevance"]

    def _select(budget: float):
        if not unconstrained:
            return None
        floor = budget * unconstrained
        affordable = [
            v for v in MIN_FRESH_CANDIDATE_VALUES
            if (by_value[str(v)]["mean_slate_relevance"] or 0.0) >= floor
        ]
        return max(affordable) if affordable else None

    by_budget = {f"{b:.2f}": _select(b) for b in (0.90, 0.95, 0.99)}

    return {
        "sample_impressions": len(selected),
        "sampling": _describe_tuning_sample(scored_rows, selected, seed=sample_seed),
        "by_min_fresh_value": by_value,
        "selection_rule": (
            "largest minimum-fresh quota whose mean slate relevance stays within a "
            "given budget of the unconstrained slate"
        ),
        "value_selected_by_relevance_budget": by_budget,
        "currently_configured_min_fresh_in_slate": DEFAULT_MIN_FRESH_IN_SLATE,
        "budgets_supporting_current_configuration": [
            b for b, v in by_budget.items() if v == DEFAULT_MIN_FRESH_IN_SLATE
        ],
    }


def verify_freshness_threshold() -> dict:
    """Redoes the freshness-candidate-coverage measurement that
    originally justified a 12-hour threshold and a minimum of 2 fresh
    items per slate, against the tune fold instead of validation, and
    separately compares real coverage across alternative threshold
    values -- not only the currently-configured value's own behavior.
    """
    train_behaviors = load_split("train")
    first_seen = compute_first_seen(train_behaviors)
    impression_time = train_behaviors.set_index("impression_id")["time"]

    train_rows, feature_provenance = _load_tuning_rows()
    fit_rows, tune_rows = split_train_for_tuning(train_rows)
    _fit_rows = fit_rows

    at_configured_threshold = _coverage_at_threshold(
        tune_rows, impression_time, first_seen, DEFAULT_FRESH_THRESHOLD_DAYS
    )
    fresh_row_rate = at_configured_threshold["fresh_row_rate"]
    return {
        "feature_provenance": feature_provenance,
        "original_validation_fresh_row_rate": ORIGINAL_VALIDATION_FRESH_ROW_RATE,
        "tune_fold_fresh_row_rate": fresh_row_rate,
        "original_validation_zero_fresh_impression_rate": ORIGINAL_VALIDATION_ZERO_FRESH_IMPRESSION_RATE,
        "tune_fold_zero_fresh_impression_rate": at_configured_threshold["zero_fresh_impression_rate"],
        "decision_confirmed": fresh_row_rate is not None and 0.2 <= fresh_row_rate <= 0.5,
        "impressions_checked": at_configured_threshold["impressions_checked"],
        "currently_configured_min_fresh_in_slate": DEFAULT_MIN_FRESH_IN_SLATE,
        "threshold_value_comparison": _compare_freshness_threshold_values(
            tune_rows, impression_time, first_seen
        ),
        "min_fresh_value_comparison": _compare_min_fresh_values(
            _score_with_held_out_model(tune_rows, _fit_rows),
            load_catalog().set_index("news_id")["category"],
            first_seen,
            impression_time,
        ),
    }


# The measured p99 for the whole request path is ~17 ms
# (docs/experiments/serving-latency.md), of which Faiss search is ~1 ms. This budget
# is the room a deeper search may take *for the search itself* before it
# stops being free relative to the stages around it -- stated here,
# before the numbers below are produced, rather than chosen to justify
# whichever depth wins.
RETRIEVAL_SEARCH_P99_BUDGET_MS = 5.0
RETRIEVAL_DEPTH_SAMPLE_IMPRESSIONS = 400


def verify_retrieval_depth(
    sample_impressions: int = RETRIEVAL_DEPTH_SAMPLE_IMPRESSIONS,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
) -> dict:
    """Measures what retrieval depth actually buys, against the tuning
    fold rather than `validation`.

    Depth is the number of candidates the serving path pulls from the
    index before ranking. Recall rises monotonically with it, so a rule
    stated purely in recall terms would always pick the deepest value
    tried -- the same defect that made the first diversity-cap rule
    meaningless. The real cost of depth is search latency, so the rule
    bounds that instead: take the deepest value whose measured p99
    search time stays inside `RETRIEVAL_SEARCH_P99_BUDGET_MS`.

    Run against the tuning fold specifically because changing retrieval
    depth is a hyperparameter decision, and this project's own history
    of making those on `validation` and then reporting against it is the
    reason `docs/experiments/evaluation-integrity.md` exists.
    """
    import time as time_module

    from recommender.evaluation.tuning_fold import split_train_for_tuning
    from recommender.serving.pipeline import build_serving_context, encode_recent_history

    context = build_serving_context()
    train_rows, feature_provenance = _load_tuning_rows()
    _fit_rows, tune_rows = split_train_for_tuning(train_rows)

    train_behaviors = load_split("train")
    history_by_impression = train_behaviors.set_index("impression_id")["history"]

    selected = sample_impression_ids(tune_rows, sample_impressions, seed=sample_seed)
    sample = tune_rows[tune_rows["impression_id"].isin(selected)]

    queries = []
    clicked_rows = []
    for impression_id, group in sample.groupby("impression_id", sort=False):
        clicked = set(group.loc[group["clicked"] == 1, "news_id"])
        if not clicked:
            continue
        history_raw = history_by_impression.get(impression_id)
        history_ids = history_ids_from_raw(history_raw) if isinstance(history_raw, str) else []
        if not history_ids:
            continue
        hist_cat, hist_subcat, hist_mask, hist_content = encode_recent_history(
            history_ids, context.item_vocab,
            item_content=context.item_content,
            item_row_by_news_id=context.item_row_by_news_id,
        )
        with torch.no_grad():
            emb = context.two_tower_model.user_vector(
                torch.from_numpy(hist_cat), torch.from_numpy(hist_subcat),
                torch.from_numpy(hist_mask), torch.from_numpy(hist_content),
            ).numpy()
        queries.append(emb[0])
        clicked_rows.append(clicked)

    if not queries:
        return {"impressions_measured": 0}

    query_matrix = np.asarray(queries, dtype=np.float32)
    by_depth: dict[str, dict] = {}
    for depth in (50, 100, 200, 500, 1000):
        _scores, rows = context.faiss_index.search(query_matrix, depth)
        contained = sum(
            1 for i, clicked in enumerate(clicked_rows)
            if clicked & set(context.news_ids[rows[i]])
        )
        # Per-query search time, measured one query at a time because
        # that is how a real request issues it -- a batched search
        # amortizes cost a live single-request path never gets.
        timings = []
        for row in query_matrix:
            start = time_module.perf_counter()
            context.faiss_index.search(row.reshape(1, -1), depth)
            timings.append((time_module.perf_counter() - start) * 1000)
        by_depth[str(depth)] = {
            "retrieval_contained_a_click_rate": contained / len(clicked_rows),
            "search_p50_ms": float(np.percentile(timings, 50)),
            "search_p99_ms": float(np.percentile(timings, 99)),
        }

    within_search_budget = [
        int(depth) for depth, stats in by_depth.items()
        if stats["search_p99_ms"] <= RETRIEVAL_SEARCH_P99_BUDGET_MS
    ]

    return {
        "feature_provenance": feature_provenance,
        "sampling": _describe_tuning_sample(tune_rows, selected, seed=sample_seed),
        "impressions_measured": len(clicked_rows),
        "split": "tuning fold carved from train (never validation)",
        "by_depth": by_depth,
        "search_p99_budget_ms": RETRIEVAL_SEARCH_P99_BUDGET_MS,
        "depths_within_search_budget": within_search_budget,
        # Reported as a tradeoff table, not as a rule that picks a
        # winner. The predefined search-latency budget turned out not to
        # bind at any depth tried -- every one came in under a
        # millisecond -- so a "deepest affordable" rule would have
        # degenerated to "deepest tried", which settles nothing, exactly
        # the defect that made the first diversity-cap rule meaningless.
        # Index search is also not where depth actually costs: ranking
        # and reranking both scale with the candidate count, so the real
        # cost has to be read from end-to-end request latency measured
        # separately (docs/experiments/serving-latency.md), not from this column.
        "selection_rule": (
            "none -- reported as a recall/latency tradeoff for a judgment call, "
            "because the search-latency budget did not bind at any depth tried"
        ),
        "currently_configured_depth": max(
            TOP_K * RETRIEVAL_MULTIPLIER, MIN_RETRIEVAL_CANDIDATES
        ),
    }


def main() -> None:
    from recommender.evaluation.publish import output_dir_from_argv, publish_tuning_report

    report = {
        "popularity_exclusion": verify_popularity_exclusion(),
        "popularity_exclusion_temporal_split_diagnostic": verify_popularity_exclusion_with_temporal_split(),
        "diversity_cap": verify_diversity_cap(),
        "freshness_threshold": verify_freshness_threshold(),
        "retrieval_depth": verify_retrieval_depth(),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    # Every section here draws its own sample; the diversity-cap section's
    # description stands for the run, and each section carries its own
    # alongside its numbers.
    published = publish_tuning_report(
        report, sampling=collect_sampling(report), output_dir=output_dir_from_argv()
    )
    print(json.dumps(report, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
