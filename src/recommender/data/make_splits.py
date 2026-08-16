import json
from pathlib import Path

import pandas as pd

from recommender.data.splits import assert_no_time_leakage, time_aware_split

PROCESSED_DIR = Path("data/processed/mind_small")
SPLITS_DIR = PROCESSED_DIR / "splits"


def main() -> None:
    train_behaviors = pd.read_parquet(PROCESSED_DIR / "train" / "behaviors.parquet")
    dev_behaviors = pd.read_parquet(PROCESSED_DIR / "dev" / "behaviors.parquet")

    train, validation = time_aware_split(train_behaviors, validation_days=1)
    assert_no_time_leakage(train, validation, dev_behaviors)

    named = {"train": train, "validation": validation, "replay": dev_behaviors}
    report = {}
    for name, df in named.items():
        split_dir = SPLITS_DIR / name
        split_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(split_dir / "behaviors.parquet", index=False)
        report[name] = {
            "rows": len(df),
            "time_start": df["time"].min().isoformat(),
            "time_end": df["time"].max().isoformat(),
        }

    report_path = SPLITS_DIR / "split_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
