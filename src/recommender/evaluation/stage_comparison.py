"""Publishes the three pipeline stages side by side.

    python -m recommender.evaluation.stage_comparison [--output-dir DIR]

Stage comparison is a join, not a new measurement: retrieval-only and
ranked come from the ranking evaluation, reranked from the reranking
evaluation. Both must have been run against the same artifact bundle in
the same rebuild, so this module reads their local reports rather than
recomputing, and refuses to publish if either is missing.

Publishing it as its own report means the prose table has a single
machine-readable source, instead of a reader having to align two reports
by hand and hope the runs matched.
"""

from __future__ import annotations

import json

from recommender.evaluation.evaluate_ranking import REPORT_PATH as RANKING_REPORT_PATH
from recommender.evaluation.evaluate_reranking import (
    REPORT_PATH as RERANKING_REPORT_PATH,
)
from recommender.evaluation.publish import (
    output_dir_from_argv,
    publish_stage_comparison_report,
)


def build_stage_comparison() -> dict:
    missing = [
        str(path)
        for path in (RANKING_REPORT_PATH, RERANKING_REPORT_PATH)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "stage comparison needs both evaluations from the same rebuild; "
            f"missing: {missing}"
        )

    ranking = json.loads(RANKING_REPORT_PATH.read_text())
    reranking = json.loads(RERANKING_REPORT_PATH.read_text())

    # The reranking run records the ranked slate it started from. If that
    # disagrees with the ranking evaluation, the two runs saw different
    # artifacts and comparing them would invent a result neither measured.
    ranked = ranking["ranked"]
    ranked_only = reranking["ranked_only"]
    for metric in ("hit_rate_at_k", "recall_at_k", "ndcg_at_k"):
        if (
            metric in ranked
            and metric in ranked_only
            and abs(ranked[metric] - ranked_only[metric]) > 1e-9
        ):
            raise ValueError(
                "ranking and reranking evaluations disagree on the ranked "
                f"slate ({metric}: {ranked[metric]} vs {ranked_only[metric]}); "
                "re-run both against the same artifact bundle"
            )

    return {
        "retrieval": ranking["retrieval_score_only"],
        "ranked": ranked,
        "reranked": reranking["reranked"],
    }


def main() -> None:
    stages = build_stage_comparison()
    published = publish_stage_comparison_report(
        stages["retrieval"],
        stages["ranked"],
        stages["reranked"],
        output_dir=output_dir_from_argv(),
    )
    print(json.dumps(stages, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
