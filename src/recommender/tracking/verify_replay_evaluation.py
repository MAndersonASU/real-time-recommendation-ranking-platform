import json
from pathlib import Path

from recommender.serving.pipeline import build_serving_context
from recommender.tracking.experiment_log import log_run
from recommender.tracking.replay_evaluation import evaluate_via_replay

REPORT_PATH = Path("data/processed/mind_small/replay_evaluation_report.json")


def main() -> None:
    context = build_serving_context()
    report = evaluate_via_replay(context)
    log_run(
        "full_system_replay_k10",
        params={"k": report["k"], "impressions_sampled": report["impressions_sampled"], "split": "replay"},
        metrics={"hit_rate_at_k": report["hit_rate_at_k"]},
        notes=(
            "Phase 9 replay evaluation -- real full pipeline (retrieval+ranking+reranking) against real "
            "replay-split impressions; a replay simulation, not a live A/B test"
        ),
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
