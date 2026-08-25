"""Regenerates the committed machine-readable evaluation reports.

Run by a maintainer who has the licensed MIND dataset locally:

    python -m recommender.evaluation.generate_reports

Reads the JSON reports each evaluation script already writes under
`data/processed/` and republishes them under `reports/` with full
provenance attached. Deliberately a separate step rather than something
the evaluation scripts do themselves: publishing a number is a distinct
decision from measuring it, and this keeps the measurement scripts
usable for exploration without every run rewriting published results.

Nothing licensed is copied -- only aggregate metrics.
"""

import json
from pathlib import Path

from recommender.evaluation.reports import write_report

DATA_DIR = Path("data/processed/mind_small")

MIND_DATASET = {
    "name": "MIND small",
    "edition": "2019-11-09 to 2019-11-15",
    "redistributed": False,
    "source": "docs/dataset-source.md",
}

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


def _load(name: str) -> dict | None:
    path = DATA_DIR / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _retrieval_report(raw: dict) -> dict:
    return {
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
                "untouched final generalization estimate."
            ),
        ],
    }


def _end_to_end_report(raw: dict) -> dict:
    return {
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
        ],
    }


def _tuning_report(raw: dict) -> dict:
    return {
        "report_name": "tuning-decisions",
        "dataset": {**MIND_DATASET, "split": "tuning fold carved from train"},
        "configuration": {
            "split": "fit/tune fold from train; validation is never used here",
            "selection_rules": "cost-bounded (relevance or latency budgets)",
        },
        "denominators": {"see_individual_sections": True},
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


def _explanation_report(raw: dict) -> dict:
    return {
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


BUILDERS = {
    "retrieval_evaluation_report.json": _retrieval_report,
    "end_to_end_evaluation_report.json": _end_to_end_report,
    "tuning_decisions_verification_report.json": _tuning_report,
    "explanation_evaluation_report.json": _explanation_report,
}


def main() -> None:
    written, missing = [], []
    for filename, builder in BUILDERS.items():
        raw = _load(filename)
        if raw is None:
            missing.append(filename)
            continue
        from recommender.evaluation.reports import build_report

        report = build_report(**builder(raw))
        written.append(str(write_report(report)))

    for path in written:
        print(f"wrote {path}")
    for filename in missing:
        # Named rather than silently skipped: a missing input means that
        # evaluation has not been run on this machine, and the published
        # report for it is therefore not being refreshed.
        print(f"skipped (no local result at {DATA_DIR / filename}): {filename}")


if __name__ == "__main__":
    main()
