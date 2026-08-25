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


def _publish(spec: dict, evaluation_module: str, sampling: dict):
    return write_report(
        build_report(evaluation_module=evaluation_module, sampling=sampling, **spec)
    )


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
                "docs/known-limitations.md records this."
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
        "denominators": {
            "sampled_impressions": raw.get("sampled_impressions"),
            "see_individual_sections": True,
        },
        "metric_definitions": {
            "cap_selected_by_relevance_budget": (
                "diversity cap chosen by the highest distinct-category count whose mean "
                "slate relevance stays within a given budget of the uncapped slate"
            ),
            "value_selected_by_relevance_budget": (
                "minimum-fresh quota chosen the same way, against the unconstrained slate"
            ),
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
    return _publish(spec, "recommender.evaluation.verify_tuning_decisions", sampling)


def publish_explanation_report(raw: dict, sampling: dict = FULL_POPULATION):
    spec = {
        "report_name": "explanation-evaluation",
        "dataset": {**MIND_DATASET, "split": "validation"},
        "configuration": {
            "mode": "deterministic templates; generative rewriting off by default",
        },
        "denominators": {"explanations_evaluated": raw.get("explanations_evaluated")},
        "metric_definitions": {
            "lexical_policy_pass_rate": (
                "share of produced explanations containing no vocabulary outside the "
                "approved template plus grammatical scaffolding. A lexical property "
                "only -- it does not establish semantic faithfulness."
            ),
            "explanations_evaluated": "count of explanations produced and checked",
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
