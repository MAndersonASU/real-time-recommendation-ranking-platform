"""Ranking features for tuning, built without any tune-fold influence.

`build_dataset.py` produces the feature table the deployed ranking model
is trained on. Two things in it disqualify it as evidence about the
tuning fold:

1. `retrieval_score` comes from the retrieval model trained on all of
   `train`, tuning fold included.
2. `build_feature_context` -- popularity counts, first-seen dates, the
   content vectors -- is fitted on all of `train` too.

Either one is enough to let tune-fold information reach a number that is
then presented as held out. This module rebuilds the same features with
both sources restricted to the fit half: the fit-only retrieval model
from `recommender.retrieval.train_fit_only`, and a feature context fitted
on fit rows alone.

Rows for the *whole* training split are still produced, fit and tune
alike -- the tuning check needs fit rows to train a ranking model on and
tune rows to score. What matters is that no feature value on either side
was computed with knowledge drawn from the tune half.

Output goes to its own file. The deployed table is not touched:

    python -m recommender.ranking.build_dataset_fit_only
"""

import json

from recommender.evaluation.contract import load_catalog, load_split
from recommender.evaluation.tuning_fold import TUNE_FOLD_SEED, split_train_for_tuning
from recommender.paths import mind_small_path
from recommender.ranking.build_dataset import RANKING_DIR
from recommender.ranking.features import FEATURE_COLUMNS, build_feature_context, build_ranking_rows
from recommender.retrieval.build_index import load_trained_model
from recommender.retrieval.content_artifact import load_item_content
from recommender.retrieval.features import build_item_vocab
from recommender.retrieval.train_fit_only import FIT_ONLY_CONTENT_PATH, FIT_ONLY_MODEL_PATH

FIT_ONLY_TRAIN_PATH = RANKING_DIR / "train_fit_only.parquet"
FIT_ONLY_DATASET_REPORT_PATH = mind_small_path("ranking_dataset_fit_only_report.json")


class FitOnlyArtifactsMissing(FileNotFoundError):
    """The fit-half retrieval bundle has not been built on this machine."""


def build_and_save() -> dict:
    if not FIT_ONLY_MODEL_PATH.exists() or not FIT_ONLY_CONTENT_PATH.exists():
        raise FitOnlyArtifactsMissing(
            "the fit-half retrieval bundle is missing. Run "
            "`python -m recommender.retrieval.train_fit_only` first; the deployed "
            "model must not be substituted here, because it was trained on the "
            "tuning fold these features are meant to be blind to."
        )

    train = load_split("train")
    fit_rows, tune_rows = split_train_for_tuning(train)
    news = load_catalog()

    _item_vocab, categories, subcategories = build_item_vocab(news)
    model = load_trained_model(
        len(categories) + 1, len(subcategories) + 1, path=FIT_ONLY_MODEL_PATH
    )
    # The fit-half model's own content matrix, not the deployed one: a
    # model scores correctly only against the basis it was trained
    # against, and these are two independent SVD fits.
    item_content = load_item_content(news, path=FIT_ONLY_CONTENT_PATH)

    # Fitted on fit rows only. Popularity and first-seen are aggregates
    # over behaviour, so fitting them on all of `train` would carry tune
    # -fold click counts into every tune-fold feature value.
    context = build_feature_context(fit_rows, news, model, item_content=item_content)

    rows = build_ranking_rows(train, context)

    RANKING_DIR.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(FIT_ONLY_TRAIN_PATH, index=False)

    report = {
        "bundle": "tuning_fit_only",
        "feature_columns": FEATURE_COLUMNS,
        "tune_fold_seed": TUNE_FOLD_SEED,
        "fit_impressions": int(fit_rows["impression_id"].nunique()),
        "tune_impressions": int(tune_rows["impression_id"].nunique()),
        "rows": len(rows),
        "positive_rate": float(rows["clicked"].mean()),
        "retrieval_model": str(FIT_ONLY_MODEL_PATH),
        "feature_context_fitted_on": "fit half only",
    }
    FIT_ONLY_DATASET_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(build_and_save(), indent=2))


if __name__ == "__main__":
    main()
