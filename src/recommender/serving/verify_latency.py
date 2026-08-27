import json
from pathlib import Path

import numpy as np

from recommender.evaluation.contract import load_split
from recommender.serving.contract import RecommendationRequest
from recommender.serving.pipeline import build_serving_context, recommend

REPORT_PATH = Path("data/processed/mind_small/latency_by_stage_report.json")


def _percentile(values: list, pct: float) -> float:
    return float(np.percentile(np.array(values), pct))


def verify_latency_by_stage(num_users: int = 100) -> dict:
    """Runs the real inference path for real validation users, collecting
    every stage's timing on every call, and reports p50/p95/p99 per
    stage plus the same for total request time -- not just one end-to-end
    number, per the phase's own stated exit criterion.
    """
    context = build_serving_context()
    users = load_split("validation")["user_id"].drop_duplicates().head(num_users).tolist()

    per_stage: dict[str, list] = {}
    totals: list = []
    for user_id in users:
        request = RecommendationRequest(user_id=user_id, num_candidates=10)
        stage_timings: dict[str, float] = {}
        recommend(request, context, stage_timings=stage_timings)
        for stage, ms in stage_timings.items():
            per_stage.setdefault(stage, []).append(ms)
        totals.append(sum(stage_timings.values()))

    report = {
        "requests_measured": len(users),
        "by_stage": {
            stage: {
                "p50_ms": round(_percentile(values, 50), 3),
                "p95_ms": round(_percentile(values, 95), 3),
                "p99_ms": round(_percentile(values, 99), 3),
            }
            for stage, values in per_stage.items()
        },
        "total": {
            "p50_ms": round(_percentile(totals, 50), 3),
            "p95_ms": round(_percentile(totals, 95), 3),
            "p99_ms": round(_percentile(totals, 99), 3),
        },
    }
    return report


def main() -> None:
    from recommender.evaluation.publish import (
        output_dir_from_argv,
        publish_serving_latency_report,
    )

    report = verify_latency_by_stage()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    published = publish_serving_latency_report(
        report, output_dir=output_dir_from_argv()
    )
    print(json.dumps(report, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
