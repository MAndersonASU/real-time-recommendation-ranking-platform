"""The minimum-fresh quota experiment specified in
`docs/experiments/min-fresh-experiment-protocol.md`.

That protocol was frozen and committed **before** this ran. The
selection rule below is a transcription of it, not a fresh decision, and
it is not to be adjusted after seeing output. If the rule picks a value
other than the deployed quota of 2, the choice is to accept it or to
record 2 as an explicit override.

Two design points worth stating, because both change what the result
means:

**Held-out clicks, not predicted score.** The earlier comparison ranked
quotas by mean predicted relevance -- what the model thinks a slate is
worth. This scores each slate against what the user actually clicked.
A quota that reorders a slate can look expensive under the model and
cost nothing in observed clicks, or the reverse.

**Paired, clustered by user.** Every quota is applied to the *same*
scored candidate set for the *same* impression, so differences are
measured within an impression rather than between samples. Bootstrap
resampling then draws whole users, because impressions from one person
are not independent observations -- their habits drive all of them, and
resampling impressions would understate the interval.

Structure follows the cost. Retrieval and ranking are the expensive
part, so each impression is scored **once**, then all five quotas are
applied to copies of that one scored candidate set. Per-user outcomes
are written to disk, and the bootstrap runs from that file -- so the
resampling stage needs no Redis, no models, and no licensed data
reload.

    python -m recommender.evaluation.min_fresh_experiment
"""

import json
from collections import defaultdict

import numpy as np
import pandas as pd

from recommender.evaluation.contract import TOP_K, load_catalog, load_split
from recommender.evaluation.metrics import hit_rate_at_k, ndcg_at_k
from recommender.evaluation.tuning_fold import split_train_for_tuning
from recommender.paths import mind_small_path
from recommender.ranking.baselines import build_content_vectors
from recommender.ranking.train import MODEL_FEATURE_COLUMNS, train_ranking_model
from recommender.reranking.diversity import build_diverse_slate
from recommender.reranking.freshness import (
    DEFAULT_FRESH_THRESHOLD_DAYS,
    apply_freshness_quota,
    compute_age_days,
    compute_first_seen,
)

OUTCOMES_PATH = mind_small_path("min_fresh_experiment_outcomes.parquet")

# The commit whose code scored the fold. Recorded explicitly because a
# re-analysis publishes from a later commit, and a report that named only
# the publishing commit would misattribute the numbers -- the same defect
# EVAL-PROVENANCE-01 closed.
SCORING_COMMIT = "bcd673102dd2c3b4a0462cacf90cda7f4031a791"

# --- frozen protocol constants -----------------------------------------
# Transcribed from docs/experiments/min-fresh-experiment-protocol.md. Changing any of
# these after seeing output would make the experiment worthless.
QUOTAS = (0, 1, 2, 3, 5)
BASELINE_QUOTA = 0
NDCG_RETENTION_FLOOR = 0.99
HIT_RATE_RETENTION_FLOOR = 0.95
CONFIDENCE = 0.95
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260826
DEPLOYED_QUOTA = 2


def score_fold(limit: int | None = None) -> pd.DataFrame:
    """One scoring pass over the tuning fold; five quotas per impression.

    Returns one row per (user, impression, quota) with that slate's
    outcome. The ranking model is fit on the fit half so it never saw
    these impressions' labels.
    """
    from recommender.evaluation.verify_tuning_decisions import _load_tuning_rows

    feature_rows, provenance = _load_tuning_rows()
    fit_rows, tune_rows = split_train_for_tuning(feature_rows)

    model = train_ranking_model(fit_rows)
    scored = tune_rows.assign(
        ranked_score=model.predict_proba(tune_rows[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    )

    news = load_catalog()
    category_by_id = news.set_index("news_id")["category"]
    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)

    behaviors = load_split("train")
    impression_time = behaviors.set_index("impression_id")["time"]
    user_by_impression = behaviors.set_index("impression_id")["user_id"]
    first_seen = compute_first_seen(behaviors)

    impression_ids = scored["impression_id"].drop_duplicates()
    if limit is not None:
        impression_ids = impression_ids.iloc[:limit]
    eligible = scored[scored["impression_id"].isin(impression_ids)]

    records = []
    for impression_id, group in eligible.groupby("impression_id", sort=False):
        if impression_id not in impression_time.index:
            continue
        if int(group["clicked"].sum()) == 0:
            # No observed click: every quota scores zero and the
            # impression carries no information about relevance cost.
            continue

        aged = group.assign(
            age_days=compute_age_days(
                group, pd.Timestamp(impression_time.loc[impression_id]), first_seen
            )
        )
        # Scored once. Every quota below reranks a copy of this.
        base_slate = build_diverse_slate(
            aged, "ranked_score", TOP_K, category_by_id, tfidf_vectors, tfidf_row_by_id
        )
        user_id = user_by_impression.get(impression_id)

        for quota in QUOTAS:
            slate = base_slate.copy()
            if quota > 0:
                slate = apply_freshness_quota(
                    slate, aged, "ranked_score", min_fresh_in_slate=quota
                )
            relevance = slate["clicked"].to_numpy()
            fresh_count = int((slate["age_days"] <= DEFAULT_FRESH_THRESHOLD_DAYS).sum())
            records.append(
                {
                    "user_id": str(user_id),
                    "impression_id": impression_id,
                    "quota": quota,
                    "ndcg_at_k": ndcg_at_k(relevance, TOP_K),
                    "hit_rate_at_k": hit_rate_at_k(relevance, TOP_K),
                    "mean_slate_relevance": float(slate["ranked_score"].sum()),
                    "fresh_items": fresh_count,
                    "meets_quota": int(fresh_count >= quota),
                    "distinct_categories": int(
                        slate["news_id"].map(category_by_id).nunique()
                    ),
                }
            )

    outcomes = pd.DataFrame.from_records(records)
    outcomes.attrs["feature_provenance"] = provenance
    return outcomes


def _paired_bootstrap_lower_bound(
    by_user: dict, quota: int, metric: str, rng: np.random.Generator
) -> dict:
    """One-sided lower confidence bound on retention versus quota 0.

    Resamples **users**, not impressions. Each draw takes a user's whole
    set of impressions, preserving the within-user correlation that
    makes impression-level resampling too optimistic.
    """
    users = list(by_user)
    baseline_totals = np.array([by_user[u][BASELINE_QUOTA][metric] for u in users])
    quota_totals = np.array([by_user[u][quota][metric] for u in users])
    counts = np.array([by_user[u][BASELINE_QUOTA]["n"] for u in users])

    observed_baseline = baseline_totals.sum() / counts.sum()
    observed_quota = quota_totals.sum() / counts.sum()
    observed_retention = (
        observed_quota / observed_baseline if observed_baseline else float("nan")
    )

    indices = rng.integers(0, len(users), size=(BOOTSTRAP_RESAMPLES, len(users)))
    resampled_baseline = baseline_totals[indices].sum(axis=1)
    resampled_quota = quota_totals[indices].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        retentions = np.where(
            resampled_baseline > 0, resampled_quota / resampled_baseline, np.nan
        )
    retentions = retentions[np.isfinite(retentions)]

    lower = float(np.quantile(retentions, 1 - CONFIDENCE)) if retentions.size else float("nan")
    return {
        "observed_baseline": float(observed_baseline),
        "observed_value": float(observed_quota),
        "observed_retention": float(observed_retention),
        "paired_difference": float(observed_quota - observed_baseline),
        "retention_lower_bound_95": lower,
    }


def analyse(outcomes: pd.DataFrame) -> dict:
    """Applies the frozen selection rule to stored per-user outcomes.

    Reads only the outcomes table, so this stage needs no models, no
    Redis and no licensed reload.
    """
    by_user: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for row in outcomes.itertuples(index=False):
        bucket = by_user[row.user_id][row.quota]
        bucket["ndcg_at_k"] += row.ndcg_at_k
        bucket["hit_rate_at_k"] += row.hit_rate_at_k
        bucket["n"] += 1

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    per_quota: dict = {}
    for quota in QUOTAS:
        subset = outcomes[outcomes["quota"] == quota]
        per_quota[str(quota)] = {
            "ndcg_at_10": _paired_bootstrap_lower_bound(by_user, quota, "ndcg_at_k", rng),
            "hit_rate_at_10": _paired_bootstrap_lower_bound(
                by_user, quota, "hit_rate_at_k", rng
            ),
            # Diagnostics. Reported, never part of the rule.
            "diagnostics": {
                "mean_slate_relevance": float(subset["mean_slate_relevance"].mean()),
                "mean_fresh_items_in_slate": float(subset["fresh_items"].mean()),
                "share_of_slates_meeting_quota": float(subset["meets_quota"].mean()),
                "mean_distinct_categories": float(subset["distinct_categories"].mean()),
            },
        }

    passing = [
        quota
        for quota in QUOTAS
        if quota != BASELINE_QUOTA
        and per_quota[str(quota)]["ndcg_at_10"]["retention_lower_bound_95"]
        >= NDCG_RETENTION_FLOOR
        and per_quota[str(quota)]["hit_rate_at_10"]["retention_lower_bound_95"]
        >= HIT_RATE_RETENTION_FLOOR
    ]
    selected = max(passing) if passing else None

    return {
        "per_quota": per_quota,
        "quotas_passing_both_bounds": passing,
        "selected_quota": selected,
        "deployed_quota": DEPLOYED_QUOTA,
        "rule_selects_deployed_value": selected == DEPLOYED_QUOTA,
        "outcome_statement": (
            f"the rule selects quota {selected}"
            if selected is not None
            else "no nonzero quota satisfies both bounds, so the evidence does not "
            "support a freshness quota; keeping the deployed value is an explicit "
            "product override, not a data-selected result"
        ),
    }


def _outcomes_digest() -> str:
    import hashlib

    return hashlib.sha256(OUTCOMES_PATH.read_bytes()).hexdigest()


def main(limit: int | None = None, reuse_outcomes: bool = False) -> None:
    """Scores the fold and publishes the result.

    `reuse_outcomes` re-analyses an existing outcomes file instead of
    rescoring. The bootstrap reads only that file, so re-publishing costs
    seconds. It is honest because the outcomes file is fingerprinted into
    the report and the commit that produced it is recorded separately
    from the commit that analysed it -- the two can differ, and pretending
    otherwise would be the provenance defect this project already fixed
    once.
    """
    from recommender.evaluation.reports import source_commit

    if reuse_outcomes and OUTCOMES_PATH.exists():
        outcomes = pd.read_parquet(OUTCOMES_PATH)
        provenance = {"note": "re-analysed from stored outcomes; see scoring_commit"}
        scoring_commit = SCORING_COMMIT
    else:
        outcomes = score_fold(limit=limit)
        provenance = outcomes.attrs.get("feature_provenance", {})
        OUTCOMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        outcomes.to_parquet(OUTCOMES_PATH, index=False)
        scoring_commit = source_commit()

    result = analyse(outcomes)
    baseline_rows = outcomes[outcomes["quota"] == BASELINE_QUOTA]
    summary = {
        "experiment": "prospectively specified tuning-fold policy experiment",
        "protocol": "docs/experiments/min-fresh-experiment-protocol.md (frozen before this run)",
        "feature_provenance": provenance,
        "denominators": {
            "impressions_evaluated": int(baseline_rows["impression_id"].nunique()),
            "distinct_users": int(baseline_rows["user_id"].nunique()),
            "quotas_evaluated": list(QUOTAS),
            "slates_scored": len(outcomes),
        },
        "selection_rule": {
            "primary": f"NDCG@10 retention lower bound >= {NDCG_RETENTION_FLOOR}",
            "guardrail": f"hit rate@10 retention lower bound >= {HIT_RATE_RETENTION_FLOOR}",
            "confidence": CONFIDENCE,
            "resampling": "paired bootstrap clustered by user",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "choose": "largest quota satisfying both bounds",
        },
        "scoring_commit": scoring_commit,
        "outcomes_sha256": _outcomes_digest(),
        **result,
    }
    summary["selection_rule"].update(
        {
            "quotas_evaluated": list(QUOTAS),
            "ndcg_retention_floor": NDCG_RETENTION_FLOOR,
            "hit_rate_retention_floor": HIT_RATE_RETENTION_FLOOR,
            "bootstrap_seed": BOOTSTRAP_SEED,
        }
    )

    from recommender.evaluation.publish import (
        output_dir_from_argv,
        publish_min_fresh_experiment_report,
    )

    published = publish_min_fresh_experiment_report(
        summary,
        sampling={
            "method": (
                "no sampling -- every eligible impression in the complete tuning fold "
                "was evaluated, at every quota"
            ),
            "seed": None,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_unit": "user (clustered), not impression",
        },
        output_dir=output_dir_from_argv(),
    )
    print(json.dumps(summary, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
