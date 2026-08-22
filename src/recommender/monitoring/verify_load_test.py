import json
from pathlib import Path

from recommender.evaluation.contract import load_split
from recommender.monitoring.load_test import sweep_concurrency
from recommender.serving.pipeline import build_serving_context

REPORT_PATH = Path("data/processed/mind_small/load_test_report.json")
NUM_USERS = 50


def main() -> None:
    context = build_serving_context()
    user_ids = load_split("validation")["user_id"].drop_duplicates().head(NUM_USERS).tolist()

    reports = sweep_concurrency(context, user_ids)
    REPORT_PATH.write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
