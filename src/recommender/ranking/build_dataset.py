import json
from pathlib import Path

from recommender.evaluation.contract import load_catalog, load_split
from recommender.ranking.features import FEATURE_COLUMNS, build_feature_context, build_ranking_rows
from recommender.retrieval.build_index import load_trained_model
from recommender.retrieval.features import build_item_vocab

RANKING_DIR = Path("data/processed/mind_small/ranking")
TRAIN_PATH = RANKING_DIR / "train.parquet"
VALIDATION_PATH = RANKING_DIR / "validation.parquet"
DATASET_REPORT_PATH = Path("data/processed/mind_small/ranking_dataset_report.json")


def build_and_save() -> dict:
    train = load_split("train")
    validation = load_split("validation")
    news = load_catalog()

    _item_vocab, categories, subcategories = build_item_vocab(news)
    model = load_trained_model(len(categories) + 1, len(subcategories) + 1)
    # Fit once on train, reused for both splits -- the same discipline
    # already applied to every Phase 2 baseline (docs/baselines.md).
    context = build_feature_context(train, news, model)

    train_rows = build_ranking_rows(train, context)
    validation_rows = build_ranking_rows(validation, context)

    RANKING_DIR.mkdir(parents=True, exist_ok=True)
    train_rows.to_parquet(TRAIN_PATH, index=False)
    validation_rows.to_parquet(VALIDATION_PATH, index=False)

    report = {
        "feature_columns": FEATURE_COLUMNS,
        "train_rows": len(train_rows),
        "train_positive_rate": float(train_rows["clicked"].mean()),
        "validation_rows": len(validation_rows),
        "validation_positive_rate": float(validation_rows["clicked"].mean()),
    }
    DATASET_REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    report = build_and_save()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
