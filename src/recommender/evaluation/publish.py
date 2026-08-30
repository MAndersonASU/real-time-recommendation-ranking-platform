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

from pathlib import Path

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


def output_dir_from_argv(argv=None):
    """Reads ``--output-dir`` so a run can publish outside the repository.

    ``reports.validate`` refuses a report produced from a dirty working
    tree, because the commit it records would not describe the code that
    produced the numbers. Writing into the tree would dirty it partway
    through a multi-evaluation rebuild and fail every later run, so a
    rebuild publishes to a directory outside the tree and the reports are
    copied back in a dedicated commit afterwards.
    """
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-dir", default=None)
    args, _ = parser.parse_known_args(argv)
    return Path(args.output_dir) if args.output_dir else None


def _publish(
    spec: dict,
    evaluation_module: str,
    sampling: dict,
    extra_artifacts: dict | None = None,
    output_dir=None,
):
    report = build_report(evaluation_module=evaluation_module, sampling=sampling, **spec)
    if extra_artifacts:
        # Merged rather than replacing: the deployed artifact hashes stay
        # (they describe the code and catalog the run executed against),
        # and the run-specific ones are added beside them under their own
        # key so the two can never be confused for each other.
        report["artifacts"] = {**report["artifacts"], **extra_artifacts}
    return write_report(report) if output_dir is None else write_report(report, output_dir)


def publish_retrieval_report(raw: dict, sampling: dict = FULL_POPULATION, output_dir=None):
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
                "untouched final generalization estimate. docs/experiments/evaluation-protocol.md "
                "records the leakage-free fit-half comparison that bounds how much of "
                "this figure that development could account for."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.evaluate_retrieval", sampling, output_dir=output_dir)


def publish_end_to_end_report(raw: dict, sampling: dict, output_dir=None):
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
                "This evaluation's own isolated recent-feature store is reconciled "
                "from each impression's point-in-time history before every request "
                "(see 'state' above), so recent history is present for nearly every "
                "impression here and this report does not exercise the durable-only, "
                "empty-Redis retrieval path a live deployment sees for a returning "
                "user with no in-window activity. SERVING-DURABLE-HISTORY-69 (formerly "
                "an open limitation, now resolved) covers that path with its own "
                "dedicated evaluation: reports/durable-history-fallback.json."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.evaluate_end_to_end", sampling, output_dir=output_dir)


def publish_tuning_report(raw: dict, sampling: dict, output_dir=None):
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
        spec,
        "recommender.evaluation.verify_tuning_decisions",
        sampling,
        extra_artifacts=extra,
        output_dir=output_dir,
    )


def publish_explanation_report(raw: dict, sampling: dict, output_dir=None):
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
        # `lexical_policy_pass_rate: 1.0` in particular reads as a far stronger
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
                "denominator for lexical_policy_pass_rate"
            ),
            "lexical_policy_passed": "produced explanations that passed the lexical policy check",
            "lexical_policy_pass_rate": (
                "lexical_policy_passed / attempted. Named for what the check enforces, which is "
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
        "results": {k: v for k, v in raw.items() if k != "sampling"},
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "A lexical pass rate is not a semantic guarantee: approved words can be "
                "reordered into unsupported claims, as "
                "tests/test_explanation_generation.py demonstrates directly."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.evaluate_explanations", sampling, output_dir=output_dir)


def publish_min_fresh_experiment_report(raw: dict, sampling: dict, output_dir=None):
    """Publishes the prospectively specified min-fresh policy experiment.

    Named as an experiment rather than an evaluation because that is what
    it is: a rule declared and committed before the run, applied to its
    output without adjustment. `docs/experiments/min-fresh-experiment-protocol.md`
    is the frozen protocol, and the commit that added it precedes the
    commit that produced these numbers.
    """
    spec = {
        "report_name": "min-fresh-experiment",
        "dataset": {**MIND_DATASET, "split": "complete tuning fold carved from train"},
        "configuration": {
            "protocol": "docs/experiments/min-fresh-experiment-protocol.md (frozen before the run)",
            "quotas_evaluated": raw["selection_rule"]["quotas_evaluated"],
            "primary_metric": "ndcg_at_10",
            "guardrail_metric": "hit_rate_at_10",
            "ndcg_retention_floor": raw["selection_rule"]["ndcg_retention_floor"],
            "hit_rate_retention_floor": raw["selection_rule"]["hit_rate_retention_floor"],
            "resampling": raw["selection_rule"]["resampling"],
            "resamples": raw["selection_rule"]["resamples"],
            "bootstrap_seed": raw["selection_rule"]["bootstrap_seed"],
            "scoring_commit": raw["scoring_commit"],
            "outcomes_sha256": raw["outcomes_sha256"],
        },
        "denominators": raw["denominators"],
        "metric_definitions": {
            "per_quota": (
                "one entry per candidate quota, each holding the primary and guardrail "
                "metrics and the diagnostics"
            ),
            "ndcg_at_10": (
                "NDCG@10 of the reranked slate against the impression's observed "
                "clicks. The decision metric"
            ),
            "hit_rate_at_10": (
                "share of impressions whose clicked item survives in the reranked "
                "slate. The guardrail: a reordering can preserve graded gain while "
                "pushing the clicked item out entirely"
            ),
            "observed_baseline": "the metric's value at quota 0",
            "observed_value": "the metric's value at this quota",
            "observed_retention": "observed_value / observed_baseline",
            "paired_difference": "observed_value - observed_baseline, measured within impression",
            "retention_lower_bound_95": (
                "one-sided 95% lower confidence bound on retention, from a paired "
                "bootstrap resampling whole users"
            ),
            "diagnostics": (
                "reported for interpretation and deliberately excluded from the "
                "selection rule"
            ),
            "mean_slate_relevance": "mean predicted relevance of the slate (diagnostic)",
            "mean_fresh_items_in_slate": "mean count of fresh items per slate (diagnostic)",
            "share_of_slates_meeting_quota": "share of slates satisfying the quota (diagnostic)",
            "mean_distinct_categories": "mean distinct categories after reranking (diagnostic)",
            "quotas_passing_both_bounds": "candidate quotas clearing both floors",
            "selected_quota": (
                "the largest quota clearing both floors, or null if none does. Boundary "
                "selection when every candidate passes"
            ),
            "deployed_quota": "the value currently configured in serving",
            "rule_selects_deployed_value": "whether the rule reproduces the deployed value",
            "outcome_statement": "the result stated in words",
        },
        "results": {
            "per_quota": raw["per_quota"],
            "quotas_passing_both_bounds": raw["quotas_passing_both_bounds"],
            "selected_quota": raw["selected_quota"],
            "deployed_quota": raw["deployed_quota"],
            "rule_selects_deployed_value": raw["rule_selects_deployed_value"],
            "outcome_statement": raw["outcome_statement"],
        },
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "A prospectively specified tuning-fold policy experiment, not an "
                "untouched final evaluation. No untouched final split exists in this "
                "project."
            ),
            (
                "Measured against logged clicks on a fixed, already-decided candidate "
                "set. It bounds what a freshness quota costs in observed relevance; it "
                "cannot say what a fresher slate is worth to a reader over time, which "
                "needs a live experiment this project does not attempt."
            ),
            (
                "A non-inferiority result with boundary selection. Every tested quota "
                "satisfied the offline relevance-retention bounds, so the rule -- which "
                "contained no benefit, satisfiability or diversity requirement -- "
                "selected the largest value tested, the boundary of the candidate set "
                "rather than an interior optimum. This establishes no measurable "
                "logged-click relevance loss up to that quota under the frozen "
                "candidate-list protocol; it does not establish that the selected quota "
                "is optimal or valuable to users."
            ),
            (
                "Scored against MIND's own supplied impression candidate list, not the "
                "end-to-end retrieval protocol, so it does not speak to what a quota "
                "costs on a Faiss-retrieved slate."
            ),
            (
                "Satisfiability is not part of the rule and falls sharply with the "
                "quota: reported per quota under diagnostics."
            ),
        ],
    }
    return _publish(spec, "recommender.evaluation.min_fresh_experiment", sampling, output_dir=output_dir)


# --- Candidate-list pipeline reports -------------------------------------
#
# Baselines, ranking, reranking, ablations, stage comparison, failure
# analysis and serving latency. Each is published by the run that measured
# it, so the recorded commit and artifact fingerprints describe those
# numbers rather than whatever happens to be checked out later.

_CANDIDATE_LIST_LIMITATIONS = [
    *_COMMON_LIMITATIONS,
    (
        "Scored against MIND's supplied candidate list for each impression "
        "rather than the full catalog, so these are not full-catalog "
        "retrieval numbers."
    ),
    (
        "Labels come from exposure-biased MIND logs: an item recorded as not "
        "clicked may never have been shown."
    ),
    (
        "Post-selection development evaluation on the validation split. No "
        "untouched final split remains, so these are not generalization "
        "estimates."
    ),
]

_RELEVANCE_DEFINITIONS = {
    "hit_rate_at_k": (
        "share of impressions with at least one clicked item in the served Top-K"
    ),
    "recall_at_k": (
        "clicked items in the Top-K divided by all clicked items in the impression"
    ),
    "ndcg_at_k": "normalised discounted cumulative gain over the served Top-K",
    "mrr": "mean reciprocal rank of the first clicked item in the served Top-K",
    "catalog_coverage_at_k": "share of the catalog appearing across all served slates",
    "catalog_size": "number of items in the catalog at evaluation time",
    "distinct_items_recommended": "count of unique items appearing in any served slate",
    "impressions_evaluated": "impressions the metric was computed over",
    "k": "size of the served Top-K slate",
    "model": "identifier of the baseline or model the row describes",
    "fallback_to_popularity_count": (
        "impressions where the baseline had no signal and fell back to global "
        "popularity ordering"
    ),
}

_SLATE_DEFINITIONS = {
    "mean_distinct_categories": "mean count of distinct categories in the served slate",
    "mean_max_category_count": (
        "mean size of the largest single-category group in the served slate"
    ),
    "fraction_of_slates_below_fresh_quota": (
        "share of slates holding fewer fresh items than the configured minimum"
    ),
    "mean_fresh_fraction": (
        "mean share of slate items newer than the freshness threshold"
    ),
    "mean_age_days": "mean age in days of the items in the served slate",
}

_CANDIDATE_LIST_CONFIG = {
    "candidate_source": (
        "MIND's supplied candidate list for each impression, not the full catalog"
    ),
    "k": 10,
}


def publish_baseline_report(raw, sampling=FULL_POPULATION, output_dir=None):
    spec = {
        "report_name": "baseline-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": dict(_CANDIDATE_LIST_CONFIG),
        "denominators": {
            "impressions_evaluated": raw.get("popularity", {}).get(
                "impressions_evaluated"
            ),
        },
        "metric_definitions": dict(_RELEVANCE_DEFINITIONS),
        "results": raw,
        "limitations": list(_CANDIDATE_LIST_LIMITATIONS),
    }
    return _publish(
        spec,
        "recommender.evaluation.evaluate_baseline",
        sampling,
        output_dir=output_dir,
    )


def publish_ranking_report(raw, sampling=FULL_POPULATION, output_dir=None):
    spec = {
        "report_name": "ranking-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": dict(_CANDIDATE_LIST_CONFIG),
        "denominators": {
            "impressions_evaluated": raw.get("ranked", {}).get("impressions_evaluated"),
        },
        "metric_definitions": {
            **_RELEVANCE_DEFINITIONS,
            "retrieval_score_only": (
                "candidates ordered by two-tower retrieval score alone"
            ),
            "ranked": "candidates ordered by the learned ranking model",
        },
        "results": raw,
        "limitations": list(_CANDIDATE_LIST_LIMITATIONS),
    }
    return _publish(
        spec,
        "recommender.evaluation.evaluate_ranking",
        sampling,
        output_dir=output_dir,
    )


def publish_reranking_report(raw, sampling=FULL_POPULATION, output_dir=None):
    spec = {
        "report_name": "reranking-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": dict(_CANDIDATE_LIST_CONFIG),
        "denominators": {
            "impressions_evaluated": raw.get("impressions_evaluated"),
            "k": raw.get("k"),
        },
        "metric_definitions": {**_RELEVANCE_DEFINITIONS, **_SLATE_DEFINITIONS},
        "results": {
            key: raw[key] for key in ("ranked_only", "reranked") if key in raw
        },
        "limitations": [
            *_CANDIDATE_LIST_LIMITATIONS,
            (
                "Diversity and freshness are slate-shape measurements, not user "
                "outcomes: nothing here shows a reader preferred the reranked slate."
            ),
        ],
    }
    return _publish(
        spec,
        "recommender.evaluation.evaluate_reranking",
        sampling,
        output_dir=output_dir,
    )


def publish_ablation_report(
    raw, full_model, sampling=FULL_POPULATION, output_dir=None
):
    """Publishes each ablated variant beside the full model it is measured against.

    The deltas are computed here rather than written into prose, so a
    document can never disagree with the arithmetic.
    """
    deltas = {}
    for variant, values in raw.items():
        deltas[variant] = {
            metric: {
                "absolute": values[metric] - full_model[metric],
                "relative_pct": (
                    (values[metric] - full_model[metric]) / full_model[metric] * 100.0
                ),
            }
            for metric in ("hit_rate_at_k", "recall_at_k", "ndcg_at_k")
            if metric in values and metric in full_model
        }
    spec = {
        "report_name": "ablation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": dict(_CANDIDATE_LIST_CONFIG),
        "denominators": {
            "impressions_evaluated": full_model.get("impressions_evaluated"),
        },
        "metric_definitions": {
            **_RELEVANCE_DEFINITIONS,
            "full_model": "the unmodified ranking model, for comparison",
            "deltas_vs_full_model": "variant minus full model, per metric",
            "absolute": "variant value minus full-model value, in metric units",
            "relative_pct": (
                "that absolute difference as a percentage of the full-model value"
            ),
        },
        "results": {"full_model": full_model, **raw, "deltas_vs_full_model": deltas},
        "limitations": [
            *_CANDIDATE_LIST_LIMITATIONS,
            (
                "The ranking model is retrained with the feature dropped, so "
                "this measures the feature's contribution under this "
                "architecture and training budget, not its value in general."
            ),
        ],
    }
    return _publish(
        spec, "recommender.evaluation.ablations", sampling, output_dir=output_dir
    )


def publish_stage_comparison_report(
    retrieval, ranked, reranked, sampling=FULL_POPULATION, output_dir=None
):
    spec = {
        "report_name": "stage-comparison",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": dict(_CANDIDATE_LIST_CONFIG),
        "denominators": {
            "impressions_evaluated": ranked.get("impressions_evaluated"),
        },
        "metric_definitions": {
            **_RELEVANCE_DEFINITIONS,
            **_SLATE_DEFINITIONS,
            "retrieval": "candidates ordered by retrieval score alone",
            "ranked": "candidates ordered by the learned ranking model",
            "reranked": "the ranked slate after diversity and freshness policy",
        },
        "results": {
            "retrieval": retrieval,
            "ranked": ranked,
            "reranked": reranked,
        },
        "limitations": list(_CANDIDATE_LIST_LIMITATIONS),
    }
    return _publish(
        spec,
        "recommender.evaluation.evaluate_ranking",
        sampling,
        output_dir=output_dir,
    )


def publish_failure_analysis_report(raw, sampling=FULL_POPULATION, output_dir=None):
    spec = {
        "report_name": "failure-analysis",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": dict(_CANDIDATE_LIST_CONFIG),
        "denominators": {
            "impressions_analyzed": raw.get("impressions_analyzed"),
            "k": raw.get("k"),
        },
        "metric_definitions": {
            "impressions_analyzed": "impressions the analysis was computed over",
            "k": "size of the served Top-K slate",
            "overall_miss_rate": (
                "share of impressions with no clicked item in the served Top-K"
            ),
            "by_user_history_length": (
                "miss rate grouped by the user's prior interaction count"
            ),
            "by_clicked_item_coldness": (
                "miss rate grouped by how recently the clicked item entered the "
                "catalog"
            ),
            "by_category_match": (
                "miss rate grouped by whether the clicked item's category matched "
                "the user's dominant category"
            ),
            "miss_rate": "share of impressions in this group that missed",
            "n": "impressions in this group",
            "impressions": "impressions in this group",
        },
        "results": raw,
        "limitations": [
            *_CANDIDATE_LIST_LIMITATIONS,
            (
                "A miss is disagreement with MIND's logged click, not evidence the "
                "served slate was worse."
            ),
        ],
    }
    return _publish(
        spec,
        "recommender.evaluation.failure_analysis",
        sampling,
        output_dir=output_dir,
    )


def publish_serving_latency_report(raw, sampling: dict, output_dir=None):
    spec = {
        "report_name": "serving-latency",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": {
            "measurement": "wall clock around each serving-path stage",
            "environment": "local containerized stack",
        },
        "denominators": {"requests_measured": raw.get("requests_measured")},
        "metric_definitions": {
            "requests_measured": "requests the latency figures were computed over",
            "by_stage": (
                "wall-clock milliseconds attributed to each serving-path stage"
            ),
            "total": "end-to-end wall-clock milliseconds per request",
            "mean_ms": "mean wall-clock milliseconds",
            "p50_ms": "median wall-clock milliseconds",
            "p95_ms": "95th-percentile wall-clock milliseconds",
            "p99_ms": "99th-percentile wall-clock milliseconds",
        },
        "results": {k: v for k, v in raw.items() if k != "sampling"},
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "Measured on one developer machine against the containerized "
                "demonstration stack, not production hardware."
            ),
            (
                "Latency depends on local CPU, container limits and Redis "
                "locality; absolute values are not portable."
            ),
        ],
    }
    return _publish(
        spec, "recommender.serving.verify_latency", sampling, output_dir=output_dir
    )


def publish_durable_history_fallback_report(raw: dict, sampling: dict, output_dir=None):
    """SERVING-DURABLE-HISTORY-69's dedicated evaluation: a cohort of real
    users with a usable point-in-time durable history, served against a
    genuinely empty, isolated Redis store -- the exact live condition
    that used to produce the same global-popularity slate for every such
    user regardless of how different their real histories were. Not the
    31 interactive requests that first reproduced the defect (reproduction
    evidence, not a representative sample) and not `end-to-end-evaluation.json`
    (that report's own isolated store is reconciled from point-in-time
    history before nearly every impression, so it does not exercise this
    path -- see its own limitations entry).
    """
    sampled = raw.get("impressions_in_sample")
    excluded = sum((raw.get("impressions_skipped") or {}).values())
    excluded_pct = (excluded / sampled * 100) if sampled else None
    eligibility_note = (
        "impression's user has a non-empty, catalog-valid, point-in-time "
        "durable history (a user with an empty or off-catalog history field "
        "is excluded, not counted as a zero)"
        + (
            f" -- {excluded} of {sampled} sampled impressions ({excluded_pct:.1f}%) "
            "were excluded on this run, so most sampled impressions were "
            "eligible, not most excluded"
            if sampled
            else ""
        )
    )
    spec = {
        "report_name": "durable-history-fallback",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": {
            "k": raw.get("k"),
            "ordering": "chronological by (time, impression_id)",
            "state": (
                "isolated per-run store, never seeded or written to -- a "
                "genuinely empty Redis for the entire run, not "
                "use_recent_features=False and not the shared serving "
                "context's own Redis client"
            ),
            "eligibility": eligibility_note,
        },
        "denominators": {
            "impressions_in_sample": raw.get("impressions_in_sample"),
            "impressions_evaluated": raw.get("impressions_evaluated"),
            "impressions_skipped": raw.get("impressions_skipped"),
            "eligible_users": raw.get("eligible_users"),
        },
        "metric_definitions": {
            "retrieval_history_source_counts": (
                "count of evaluated impressions by which history actually drove "
                "retrieval -- expected to be entirely 'durable' here, since the "
                "isolated store is never seeded; any other value would mean this "
                "evaluation stopped measuring the condition it claims to"
            ),
            "durable": "impressions retrieved using the user's durable history (the expected case here)",
            "recent": (
                "impressions retrieved using a recent Redis history -- should be zero here, "
                "since the isolated store is never seeded; a nonzero count means this "
                "evaluation is no longer measuring the durable-only condition it claims to"
            ),
            "global_popularity": (
                "impressions with neither usable history, retrieved by flat popularity -- "
                "excluded from this cohort's eligibility filter, so this should be zero here"
            ),
            "distinct_top_k_sets": "count of distinct top-K item sets across all evaluated impressions",
            "distinct_recommended_items": "count of unique items appearing in any served top-K slate",
            "catalog_coverage_at_k": "share of the catalog appearing across all served slates",
            "top_k_concentration": (
                "the single most frequent top-K set's share of all evaluated "
                "impressions -- 1.0 means every impression got the identical slate"
            ),
            "mean_pairwise_slate_jaccard": (
                "mean Jaccard similarity (intersection over union) over pairs of "
                "served top-K slates, sampled rather than exhaustive beyond "
                "max_jaccard_pairs pairs -- higher means less distinguishable "
                "slates across different users"
            ),
            "retrieval_contained_a_click_rate": (
                "share of impressions where the clicked item was among the "
                "retrieved candidates -- a ceiling on every metric below it"
            ),
            "hit_rate_at_k": "share of impressions whose clicked item is in the served top K",
            "recall_at_k": "share of an impression's clicked items in the served top K",
            "ndcg_at_k": "normalised discounted cumulative gain over the served top K",
            "mrr": "mean reciprocal rank of the first clicked item",
            "mean_retrieval_ms": "mean wall-clock milliseconds for the retrieval stage",
            "mean_ranking_ms": "mean wall-clock milliseconds for the ranking stage",
            "mean_total_ms": "mean wall-clock milliseconds for the full request",
        },
        "results": {
            k: raw[k]
            for k in (
                "retrieval_history_source_counts", "distinct_top_k_sets",
                "distinct_recommended_items", "catalog_coverage_at_k",
                "top_k_concentration", "mean_pairwise_slate_jaccard",
                "retrieval_contained_a_click_rate", "hit_rate_at_k", "recall_at_k",
                "ndcg_at_k", "mrr", "mean_retrieval_ms", "mean_ranking_ms", "mean_total_ms",
            )
            if k in raw
        },
        "limitations": [
            *_COMMON_LIMITATIONS,
            (
                "Eligibility is drawn from MIND's own history field, which is "
                "itself already bounded and does not document how far back it "
                "extends -- 'usable durable history' means what this dataset "
                "recorded, not necessarily a user's complete real history."
            ),
            (
                "Retrieval is the binding constraint: no ranking improvement can "
                "lift the end-to-end result above retrieval_contained_a_click_rate."
            ),
            "Does not reproduce production traffic, concurrency, or infrastructure latency.",
            (
                "Measures the durable-only fallback path in isolation, by "
                "construction (the isolated Redis is never seeded) -- it does "
                "not measure how often a live deployment's users actually reach "
                "this path versus a real recent-history one; end-to-end-evaluation.json "
                "reports recent_feature_coverage for that separate question."
            ),
        ],
    }
    return _publish(
        spec, "recommender.evaluation.evaluate_durable_history_fallback", sampling, output_dir=output_dir
    )
