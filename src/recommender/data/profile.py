import json
from pathlib import Path

import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.paths import mind_small_path

PROCESSED_DIR = mind_small_path()
SPLITS = ("train", "dev")


def profile_split(split: str, processed_dir: Path = PROCESSED_DIR) -> dict:
    split_dir = processed_dir / split
    news = pd.read_parquet(split_dir / "news.parquet")
    behaviors = pd.read_parquet(split_dir / "behaviors.parquet")

    impression_sizes = behaviors["impressions"].str.split().str.len()
    exploded = explode_impressions(behaviors)
    item_impression_counts = exploded["news_id"].value_counts()
    user_interaction_counts = behaviors["user_id"].value_counts()

    top1_share = float(item_impression_counts.iloc[0] / len(exploded))
    top10_share = float(item_impression_counts.iloc[:10].sum() / len(exploded))

    return {
        "split": split,
        "news_rows": len(news),
        "behaviors_rows": len(behaviors),
        "duplicate_news_id": int(news["news_id"].duplicated().sum()),
        "duplicate_impression_id": int(behaviors["impression_id"].duplicated().sum()),
        "news_null_abstract_rate": round(float(news["abstract"].isna().mean()), 4),
        "behaviors_null_history_rate": round(float(behaviors["history"].isna().mean()), 4),
        "distinct_users": int(behaviors["user_id"].nunique()),
        "distinct_items_impressed": int(exploded["news_id"].nunique()),
        "user_interactions_min": int(user_interaction_counts.min()),
        "user_interactions_max": int(user_interaction_counts.max()),
        "user_interactions_median": float(user_interaction_counts.median()),
        "impression_size_min": int(impression_sizes.min()),
        "impression_size_max": int(impression_sizes.max()),
        "impression_size_mean": round(float(impression_sizes.mean()), 2),
        "impression_size_median": float(impression_sizes.median()),
        "total_impression_item_pairs": len(exploded),
        "overall_click_rate": round(float(exploded["clicked"].mean()), 4),
        "item_impression_top1_share": round(top1_share, 4),
        "item_impression_top10_share": round(top10_share, 4),
        "distinct_categories": int(news["category"].nunique()),
        "distinct_subcategories": int(news["subcategory"].nunique()),
        "category_distribution": news["category"].value_counts().to_dict(),
        "time_coverage_start": behaviors["time"].min().isoformat(),
        "time_coverage_end": behaviors["time"].max().isoformat(),
    }


def main() -> None:
    report = {split: profile_split(split) for split in SPLITS}
    report_path = PROCESSED_DIR / "data_quality_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
