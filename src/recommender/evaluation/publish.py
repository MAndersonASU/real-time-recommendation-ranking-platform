"""Report shapes for each evaluation, published by the run that measures.

These builders used to live in a separate `generate_reports` step that
read a previous run's JSON off disk and stamped the current commit onto
it. That arrangement could not distinguish a fresh result from a stale
one, so the provenance it attached was decoration rather than evidence.

Each evaluation's `main()` now calls the matching builder while it still
holds its own results, and writes the published report itself. The raw
per-run JSON under `data/processed/` is still written, but it is an
intermediate now, not the source of anything published.

Only aggregate metrics appear here. Nothing row-level, no user
identifiers and no article text: the underlying dataset is licensed and
is never redistributed by this repository.
"""

from recommender.evaluation.reports import build_report, write_report

MIND_DATASET = {
    "name": "MIND small",
    "edition": "2019-11-09 to 2019-11-15",
    "redistributed": False,
    "source": "docs/dataset-source.md",
}

# Stated on every report rather than assumed known. Both facts change how
# a number should be read, and a reader who sees only the number will
# otherwise assume the ordinary case: that they could re-run it, and that
# CI checks it.
_COMMON_LIMITATIONS = [
    (
        "Computed from the licensed MIND dataset, which this repository does not "
        "redistribute, so these numbers cannot be reproduced from a public clone "
        "without supplying the dataset locally."
    ),
    (
        "Public CI verifies wiring against synthetic artifacts only; it does not "
        "reproduce any number in this report."
    ),
]

# The sampling description for an evaluation that reads its entire
# eligible population. Reported explicitly so "no sampling" is a recorded
# fact rather than an absent field a reader has to interpret.
FULL_POPULATION = {
    "method": "no sampling -- every eligible impression in the split was evaluated",
    "seed": None,
}


def _publish(spec: dict, evaluation_module: str, sampling: dict, extra_artifacts: dict | None = None):
    report = build_report(evaluation_module=evaluation_module, sampling=sampling, **spec)
    if extra_artifacts:
        # Merged rather than replacing: the deployed artifact hashes stay
        # (they describe the code and catalog the run executed against),
        # and the run-specific ones are added beside them under their own
        # key so the two can never be confused for each other.
        report["artifacts"] = {**report["artifacts"], **extra_artifacts}
    return write_report(report)


def publish_retrieval_report(raw: dict, sampling: dict = FULL_POPULATION):
    spec = {
        "report_name": "retrieval-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": {
            "n_candidates": raw.get("n"),
            "search": "exact inner-product (isolates model quality from index approximation)",
        },
        "denominators": {
            "impressions_evaluated": raw.get("impressions_evaluated"),
            "catalog_size": raw.get("catalog_size"),
        },
        "metric_definitions": {
            "hit_rate_at_n": "share of impressions whose clicked item appears in the top N",
            "recall_at_n": "share of an impression's clicked items appearing in the top N",
            "ndcg_at_n": "normalised discounted cumulative gain over the top N",
            "mrr": "mean reciprocal rank of the first clicked item",
            "catalog_coverage_at_n": "share of the catalog appearing across all recommendations",
            "distinct_items_recommended": "count of unique items appearing in any top-N list",
        },
        "results": {
            k: raw[k]
            for k in (
                "hit_rate_at_n", "recall_at_n", "ndcg_at_n", "mrr",
                "catalog_coverage_at_n", "distinct_items_recommended",
            )
            if k in raw
        },
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "Post-selection development evaluation: the content-aware item tower "
                "was developed after observing validation behaviour, so this is not an "
                "untouched final generalization estimate. docs/evaluation-protocol.md "
                "records the leakage-free fit-half comparison that bounds how much of "
                "this figure that development could account for."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.evaluate_retrieval", sampling)


def publish_end_to_end_report(raw: dict, sampling: dict):
    spec = {
        "report_name": "end-to-end-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": {
            "k": raw.get("k"),
            "ordering": "chronological by (time, impression_id)",
            "state": "isolated per-run store, reconciled from point-in-time history",
        },
        "denominators": {
            "impressions_in_sample": raw.get("impressions_in_sample"),
            "impressions_evaluated": raw.get("impressions_evaluated"),
            "impressions_skipped": raw.get("impressions_skipped"),
        },
        "metric_definitions": {
            "retrieval_contained_a_click_rate": (
                "share of impressions where the clicked item was among the retrieved "
                "candidates -- a ceiling on every metric below it"
            ),
            "hit_rate_at_k": "share of impressions whose clicked item is in the served top K",
            "recall_at_k": "share of an impression's clicked items in the served top K",
            "ndcg_at_k": "normalised discounted cumulative gain over the served top K",
            "mrr": "mean reciprocal rank of the first clicked item",
            "catalog_coverage": "share of the catalog appearing across all served slates",
            "durable_feature_coverage": "share of requests served with durable features present",
            "recent_feature_coverage": "share of requests served with recent features present",
            "fallback_count": "requests served by the cold-start fallback rather than retrieval",
        },
        "results": {
            k: raw[k]
            for k in (
                "retrieval_contained_a_click_rate", "hit_rate_at_k", "recall_at_k",
                "ndcg_at_k", "mrr", "catalog_coverage",
                "durable_feature_coverage", "recent_feature_coverage",
                "fallback_count",
            )
            if k in raw
        },
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "Retrieval is the binding constraint: no ranking improvement can lift the "
                "end-to-end result above retrieval_contained_a_click_rate."
            ),
            "Post-selection development evaluation, not an untouched final estimate.",
            "Does not reproduce production traffic, concurrency, or infrastructure latency.",
            (
                "The serving path builds its retrieval query from recent in-session "
                "clicks only, so a returning user with long durable history but no "
                "in-window activity is retrieved for as a cold start. "
                "docs/limitations.md records this."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.evaluate_end_to_end", sampling)


def publish_tuning_report(raw: dict, sampling: dict):
    spec = {
        "report_name": "tuning-decisions",
        "dataset": {**MIND_DATASET, "split": "tuning fold carved from train"},
        "configuration": {
            "split": "fit/tune fold from train; validation is never used here",
            "selection_rules": "cost-bounded (relevance or latency budgets)",
        },
        # This report's sections each carry their own counts, because each
        # comparison samples independently. The top-level denominators
        # are the ones common to all of them.
        "denominators": {
            "tune_fold_impressions": raw.get("diversity_cap", {}).get("impressions_checked"),
            "comparisons_reported": len(raw),
        },
        # Unlike the other reports, this one's results are decision
        # objects rather than scalar metrics -- each section states what
        # was compared, what the rule selected, and what is configured.
        # Every top-level key is defined, so no section is published as
        # an unexplained blob.
        "metric_definitions": {
            "popularity_exclusion": (
                "re-checks, on the tuning fold, the original decision to drop "
                "`popularity` from the ranking model. Reports the fold's out-of-sample "
                "AUC for the feature against the original validation-measured AUC"
            ),
            "popularity_exclusion_temporal_split_diagnostic": (
                "the same check against a chronologically split fold rather than a "
                "random one, testing whether short-term popularity recency leaks "
                "across a same-window random split. A diagnostic, not a decision"
            ),
            "diversity_cap": (
                "compares real slates built at several per-category cap values and "
                "reports, for each relevance budget, the cap the selection rule picks "
                "against the cap currently configured"
            ),
            "freshness_threshold": (
                "the same treatment for the freshness age threshold and the "
                "minimum-fresh-items quota, each against its own alternatives"
            ),
            "retrieval_depth": (
                "measures what retrieval depth buys against a predefined latency "
                "budget. Reported as a tradeoff table rather than a rule-selected "
                "value, because the budget did not bind at any depth tried"
            ),
            # Nested leaves. Every measurement inside the sections above
            # needs its own definition, at whatever depth it appears --
            # an invented nested field once passed validation because
            # only the five section names were checked.
            "decision_confirmed": (
                "whether the tuning fold reproduces the original decision made on "
                "validation"
            ),
            "original_validation_auc": (
                "the popularity feature's AUC as originally measured on validation -- "
                "the leaked figure this fold re-checks, recorded rather than re-derived"
            ),
            "tune_fold_auc_out_of_sample_popularity": (
                "the same feature's AUC on the tuning fold, out of sample"
            ),
            "chronological_split_tune_fold_auc": (
                "the same, on a chronologically split fold rather than a random one"
            ),
            "recency_leakage_explanation_supported": (
                "whether the chronological split reproduces the random split's result, "
                "testing whether short-term popularity recency leaks across a "
                "same-window random split"
            ),
            "ranking_model_excludes_tuning_rows": (
                "whether the ranking model scoring these rows was fit without them"
            ),
            "original_validation_four_plus_same_category_rate": (
                "share of validation slates with four or more items from one category, "
                "as originally measured"
            ),
            "tune_fold_four_plus_same_category_rate": "the same, measured on the tuning fold",
            "original_validation_single_category_rate": (
                "share of validation slates drawn entirely from one category, as "
                "originally measured"
            ),
            "tune_fold_single_category_rate": "the same, measured on the tuning fold",
            "mean_slate_relevance": (
                "mean predicted relevance of a slate under one candidate parameter "
                "value. A model score, not an observed click outcome"
            ),
            "mean_distinct_categories": "mean count of distinct categories per slate",
            "original_validation_fresh_row_rate": (
                "share of validation candidates below the freshness age threshold, as "
                "originally measured"
            ),
            "tune_fold_fresh_row_rate": "the same, measured on the tuning fold",
            "fresh_row_rate": "share of candidates below the freshness age threshold",
            "original_validation_zero_fresh_impression_rate": (
                "share of validation slates containing no fresh item, as originally "
                "measured"
            ),
            "tune_fold_zero_fresh_impression_rate": "the same, measured on the tuning fold",
            "zero_fresh_impression_rate": "share of slates containing no fresh item",
            "mean_fresh_items_in_slate": "mean count of fresh items per slate",
            "share_of_slates_meeting_quota": (
                "share of slates satisfying the minimum-fresh quota under one candidate "
                "value"
            ),
            "threshold_selected_by_rule": (
                "freshness age threshold chosen by the selection rule"
            ),
            "rule_supports_current_configuration": (
                "whether the rule's selection matches the deployed value"
            ),
            "retrieval_contained_a_click_rate": (
                "share of impressions whose clicked item appeared anywhere in the "
                "retrieved candidate pool at a given depth. A ceiling on every ranking "
                "metric, and not a top-10 measurement"
            ),
            "search_p50_ms": "median index search latency at one retrieval depth",
            "search_p99_ms": "99th-percentile index search latency at one retrieval depth",
        },
        "results": raw,
        "limitations": [
            *_COMMON_LIMITATIONS,
            "Budget values are product judgments, not results this data can settle.",
            (
                "The retrieval-depth latency budget did not bind at any depth tried, so "
                "that comparison is reported as a tradeoff table rather than a "
                "rule-selected value."
            ),
            "The chronological-split popularity check is confounded by user composition.",
        ],
    }
    # Without these, `tune_fold_leakage: false` is an assertion about
    # artifacts the report does not identify -- its generic `artifacts`
    # block describes the deployed model, which is exactly the model this
    # comparison exists to avoid using.
    from recommender.retrieval.train_fit_only import fit_only_artifact_manifest

    leakage_free = (
        raw.get("diversity_cap", {}).get("feature_provenance", {}).get("tune_fold_leakage")
        is False
    )
    extra = {"fit_only_bundle": fit_only_artifact_manifest()} if leakage_free else {}
    return _publish(
        spec, "recommender.evaluation.verify_tuning_decisions", sampling, extra_artifacts=extra
    )


def publish_explanation_report(raw: dict, sampling: dict = FULL_POPULATION):
    spec = {
        "report_name": "explanation-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": {
            "mode": "deterministic templates; generative rewriting off by default",
        },
        "denominators": {
            "total_recommendations_evaluated": raw.get("total_recommendations_evaluated"),
            "attempted": raw.get("attempted"),
        },
        # Every published number gets a definition. The previous report
        # dumped the raw result dict with a single definition covering
        # eleven metrics, so most of them were bare numbers -- and
        # `faithfulness_rate: 1.0` in particular reads as a far stronger
        # claim than what is actually measured.
        "metric_definitions": {
            "total_recommendations_evaluated": (
                "recommendations an explanation was requested for -- the denominator "
                "for refusal_rate"
            ),
            "refused": (
                "recommendations the explanation layer declined to explain, because no "
                "approved template's preconditions were satisfied by validated signals"
            ),
            "refusal_rate": "refused / total_recommendations_evaluated",
            "attempted": (
                "recommendations an explanation was actually produced for -- the "
                "denominator for faithfulness_rate"
            ),
            "faithful": "produced explanations that passed the lexical policy check",
            "faithfulness_rate": (
                "faithful / attempted. Named for what the check enforces, which is "
                "lexical, not semantic: an explanation passes when it contains no "
                "vocabulary outside its approved template plus grammatical "
                "scaffolding. Approved words can still be arranged into an "
                "unsupported claim, and tests/test_explanation_generation.py "
                "demonstrates exactly that. A rate of 1.0 means every explanation "
                "stayed inside the approved vocabulary, not that every explanation "
                "is true."
            ),
            "model_rewrite_used": (
                "explanations whose wording came from the local generative model. "
                "Zero in the default configuration, where rewriting is off"
            ),
            "template_fallback_used": (
                "explanations whose wording came from a deterministic template"
            ),
            "model_contribution_rate": "model_rewrite_used / attempted",
            "mean_explanation_length_chars": "mean character length of produced explanations",
            "distinct_explanations": (
                "count of unique explanation strings produced. A low number is "
                "expected and is a property of the template set, not a defect"
            ),
        },
        "results": raw,
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "A lexical pass rate is not a semantic guarantee: approved words can be "
                "reordered into unsupported claims, as "
                "tests/test_explanation_generation.py demonstrates directly."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.evaluate_explanations", sampling)
