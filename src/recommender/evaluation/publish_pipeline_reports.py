"""Publish sanitized machine-readable reports for the headline pipeline tables.

Reads locally generated evaluation reports (which sit under the gitignored
licensed-data tree) and republishes them under ``reports/`` with the same
envelope the other published reports use: metric definitions, denominators,
sampling, provenance and limitations.

No licensed dataset content is copied.

NOT YET USED FOR PUBLICATION. ``reports.validate`` requires
``working_tree_clean`` and a ``source_commit`` that genuinely describes the
code which produced the numbers (EVAL-PROVENANCE-01). Republishing an older
local result cannot satisfy that without asserting a provenance that is not
true, so the output of this module is deliberately not committed. To publish
these tables honestly: rebuild the offline artifacts, re-run each evaluation
from a clean tree, and publish through the normal per-report path.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from datetime import UTC, datetime

ROOT = pathlib.Path(__file__).resolve().parents[3]
LOCAL = ROOT / "data" / "processed" / "mind_small"
OUT = ROOT / "reports"

MIND = {
    "name": "MIND small",
    "edition": "2019-11-09 to 2019-11-15",
    "source": "docs/dataset-source.md",
    "redistributed": False,
    "split": "validation",
}

# Every numeric leaf a published report exposes needs a definition; the
# report schema validates that recursively.
COMMON_DEFS = {
    "impressions_evaluated": "number of impressions the metric was computed over",
    "impressions_analyzed": "number of impressions the analysis was computed over",
    "k": "size of the served Top-K slate",
    "mrr": "mean reciprocal rank of the first clicked item in the served slate",
    "catalog_coverage_at_k": "distinct items recommended divided by catalog size",
    "catalog_size": "number of items in the catalog at evaluation time",
    "distinct_items_recommended": "count of distinct items appearing in any served slate",
    "absolute": "variant value minus full-model value, in metric units",
    "relative_pct": "that absolute difference as a percentage of the full-model value",
    "model": "identifier of the baseline or model the row describes",
    "fallback_to_popularity_count": (
        "impressions where the baseline had no signal and fell back to "
        "global popularity ordering"
    ),
    "overall_miss_rate": (
        "fraction of evaluated impressions with no clicked item in the "
        "served Top-K"
    ),
    "requests_measured": "number of requests the latency figures were computed over",
    "by_stage": "wall-clock milliseconds attributed to each serving-path stage",
    "total": "end-to-end wall-clock milliseconds per request",
    "p50_ms": "median wall-clock milliseconds",
    "p95_ms": "95th-percentile wall-clock milliseconds",
    "p99_ms": "99th-percentile wall-clock milliseconds",
    "mean_ms": "mean wall-clock milliseconds",
    "miss_rate": "fraction of impressions in this group with no clicked item in the served Top-K",
    "impressions": "number of impressions in this group",
    "n": "number of impressions in this group",
    "mean_fresh_fraction": "mean fraction of slate items newer than the freshness threshold",
    "mean_age_days": "mean age in days of the items in the served slate",
    "mean_distinct_categories": (
        "mean count of distinct categories in the served slate"
    ),
    "mean_max_category_count": (
        "mean size of the largest single-category group in the slate"
    ),
    "fraction_of_slates_below_fresh_quota": (
        "fraction of slates containing fewer fresh items than the configured "
        "minimum"
    ),
}

RELEVANCE_DEFS = {
    "hit_rate_at_k": (
        "fraction of evaluated impressions with at least one clicked item "
        "in the served Top-K"
    ),
    "recall_at_k": (
        "clicked items in the Top-K divided by all clicked items in the "
        "impression"
    ),
    "ndcg_at_k": "normalized discounted cumulative gain over the served Top-K",
}

CANDIDATE_LIST_LIMITS = [
    (
        "Scored against MIND's supplied candidate list for each impression, "
        "not the full catalog, so these are not full-catalog retrieval numbers."
    ),
    (
        "Labels come from exposure-biased MIND logs: a non-clicked item may "
        "never have been shown to the user."
    ),
    (
        "Post-selection development evaluation on the validation split. No "
        "untouched final split remains, so these are not generalization "
        "estimates."
    ),
    (
        "Computed from the licensed MIND dataset, which this repository does "
        "not redistribute; a public clone cannot reproduce them without "
        "supplying the dataset locally."
    ),
]

# Copied from the artifact bundle the local reports were produced against.
ARTIFACTS = {
    "note": (
        "identifiers of the artifact bundle these results were computed "
        "against; recorded at publication from the local evaluation run"
    ),
    "embedding_dim": 32,
    "content_dim": 64,
    "ranking_feature_schema": [
        "retrieval_score",
        "category_match",
        "content_similarity",
        "user_history_length",
        "hour_of_day",
    ],
}

CONFIGURATION = {
    "candidate_source": (
        "MIND's supplied candidate list for each impression, not the full "
        "catalog"
    ),
    "k": 10,
}

LATENCY_LIMITS = [
    (
        "Measured on one developer machine against the containerized "
        "demonstration stack, not production hardware."
    ),
    (
        "Latency depends on local CPU, container limits and Redis locality; "
        "absolute values are not portable."
    ),
]


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def envelope(
    name: str,
    module: str,
    results: dict,
    defs: dict,
    denominators: dict,
    limits: list[str],
) -> dict:
    return {
        "schema_version": 2,
        "report_name": name,
        "provenance": {
            "evaluation_module": module,
            "published_at": datetime.now(UTC).isoformat(),
            "source_commit": commit(),
            "published_from": (
                "previously generated local evaluation report under "
                "data/processed/mind_small/, republished without recomputation"
            ),
        },
        "dataset": dict(MIND),
        "sampling": {
            "method": (
                "no sampling -- every eligible impression in the split was "
                "evaluated"
            ),
            "seed": None,
        },
        "artifacts": dict(ARTIFACTS),
        "configuration": dict(CONFIGURATION),
        "denominators": denominators,
        "metric_definitions": {**COMMON_DEFS, **defs},
        "results": results,
        "limitations": limits,
    }


def load(name: str) -> dict:
    return json.loads((LOCAL / f"{name}.json").read_text(encoding="utf-8"))


def write(filename: str, doc: dict) -> None:
    path = OUT / filename
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> None:
    OUT.mkdir(exist_ok=True)

    baseline = load("baseline_report")
    write(
        "baseline-evaluation.json",
        envelope(
            "baseline-evaluation",
            "recommender.ranking.baselines",
            baseline,
            RELEVANCE_DEFS,
            {
                "impressions_evaluated": baseline.get("popularity", {}).get(
                    "impressions_evaluated"
                )
            },
            CANDIDATE_LIST_LIMITS,
        ),
    )

    ranking = load("ranking_evaluation_report")
    write(
        "ranking-evaluation.json",
        envelope(
            "ranking-evaluation",
            "recommender.evaluation.evaluate_ranking",
            ranking,
            {
                **RELEVANCE_DEFS,
                "retrieval_score_only": (
                    "candidates ordered by two-tower retrieval score alone"
                ),
                "ranked": "candidates ordered by the learned ranking model",
            },
            {
                "impressions_evaluated": ranking.get("ranked", {}).get(
                    "impressions_evaluated"
                )
            },
            CANDIDATE_LIST_LIMITS,
        ),
    )

    reranking = load("reranking_evaluation_report")
    write(
        "reranking-evaluation.json",
        envelope(
            "reranking-evaluation",
            "recommender.evaluation.evaluate_reranking",
            {
                k: v
                for k, v in reranking.items()
                if k in ("ranked_only", "reranked")
            },
            RELEVANCE_DEFS,
            {
                "impressions_evaluated": reranking.get("impressions_evaluated"),
                "k": reranking.get("k"),
            },
            CANDIDATE_LIST_LIMITS,
        ),
    )

    ablation = load("ablation_report")
    full = ranking["ranked"]
    results = {"full_model": full, **ablation}
    deltas = {}
    for variant, vals in ablation.items():
        deltas[variant] = {
            metric: {
                "absolute": vals[metric] - full[metric],
                "relative_pct": (vals[metric] - full[metric]) / full[metric] * 100.0,
            }
            for metric in ("hit_rate_at_k", "recall_at_k", "ndcg_at_k")
            if metric in vals and metric in full
        }
    results["deltas_vs_full_model"] = deltas
    write(
        "ablation.json",
        envelope(
            "ablation",
            "recommender.evaluation.evaluate_ablations",
            results,
            {
                **RELEVANCE_DEFS,
                "deltas_vs_full_model": (
                    "variant minus full model; relative_pct is that difference "
                    "as a percentage of the full-model value"
                ),
            },
            {"impressions_evaluated": full.get("impressions_evaluated")},
            CANDIDATE_LIST_LIMITS,
        ),
    )

    write(
        "stage-comparison.json",
        envelope(
            "stage-comparison",
            "recommender.evaluation.evaluate_ranking",
            {
                "retrieval": ranking["retrieval_score_only"],
                "ranked": ranking["ranked"],
                "reranked": reranking["reranked"],
            },
            RELEVANCE_DEFS,
            {
                "impressions_evaluated": ranking.get("ranked", {}).get(
                    "impressions_evaluated"
                )
            },
            CANDIDATE_LIST_LIMITS,
        ),
    )

    latency = load("latency_by_stage_report")
    write(
        "serving-latency.json",
        envelope(
            "serving-latency",
            "recommender.monitoring.latency_by_stage",
            latency,
            {
                "by_stage": (
                    "wall-clock milliseconds attributed to each serving-path stage"
                ),
                "total": "end-to-end wall-clock milliseconds per request",
            },
            {"requests_measured": latency.get("requests_measured")},
            LATENCY_LIMITS,
        ),
    )

    failures = load("failure_analysis_report")
    write(
        "failure-analysis.json",
        envelope(
            "failure-analysis",
            "recommender.evaluation.analyze_failures",
            failures,
            {
                "overall_miss_rate": (
                    "fraction of evaluated impressions with no clicked item in "
                    "the served Top-K"
                ),
                "by_user_history_length": (
                    "miss rate grouped by the user's prior interaction count"
                ),
                "by_clicked_item_coldness": (
                    "miss rate grouped by how recently the clicked item entered "
                    "the catalog"
                ),
                "by_category_match": (
                    "miss rate grouped by whether the clicked item's category "
                    "matched the user's dominant category"
                ),
            },
            {
                "impressions_analyzed": failures.get("impressions_analyzed"),
                "k": failures.get("k"),
            },
            CANDIDATE_LIST_LIMITS,
        ),
    )


if __name__ == "__main__":
    main()
