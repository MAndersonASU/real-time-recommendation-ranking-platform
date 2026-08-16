import json
from pathlib import Path

from recommender.data.mind import load_behaviors, load_news

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed/mind_small")
SPLITS = ("train", "dev")


def ingest_split(split: str, raw_dir: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR) -> dict:
    split_raw = raw_dir / split
    news = load_news(split_raw / "news.tsv")
    behaviors = load_behaviors(split_raw / "behaviors.tsv")

    split_processed = processed_dir / split
    split_processed.mkdir(parents=True, exist_ok=True)
    news.to_parquet(split_processed / "news.parquet", index=False)
    behaviors.to_parquet(split_processed / "behaviors.parquet", index=False)

    return {
        "split": split,
        "news_rows": len(news),
        "behaviors_rows": len(behaviors),
        "news_null_abstract": int(news["abstract"].isna().sum()),
        "behaviors_null_history": int(behaviors["history"].isna().sum()),
        "behaviors_time_min": behaviors["time"].min().isoformat(),
        "behaviors_time_max": behaviors["time"].max().isoformat(),
    }


def main() -> None:
    report = {split: ingest_split(split) for split in SPLITS}
    report_path = PROCESSED_DIR / "ingestion_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
