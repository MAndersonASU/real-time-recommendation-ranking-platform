import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from recommender.ranking.build_dataset import TRAIN_PATH, VALIDATION_PATH
from recommender.ranking.features import FEATURE_COLUMNS

MODEL_PATH = Path("data/processed/mind_small/ranking_model.joblib")
TRAIN_REPORT_PATH = Path("data/processed/mind_small/ranking_train_report.json")

# `popularity` is deliberately excluded from the trained model, not just
# left in and hoped to wash out. A direct check (before accepting the
# first fit) found it scores *worse than random* alone on validation
# (AUC 0.47), while every other feature generalizes normally. Cause: it's
# an aggregate click count over items that repeat ~272 times on average
# within train's own exploded rows, so it partly correlates with the very
# labels it's fit on, and only 29.2% of validation candidates even have a
# nonzero train count -- the same cold-start sparsity already found for
# the collaborative baseline (docs/baselines.md). Kept in the persisted
# feature table (FEATURE_COLUMNS) for transparency; excluded here.
MODEL_FEATURE_COLUMNS = [c for c in FEATURE_COLUMNS if c != "popularity"]


def load_ranking_frame(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def train_ranking_model(train: pd.DataFrame) -> Pipeline:
    """Plain (unweighted) logistic regression over the scaled model
    features. Deliberately not class_weight="balanced" -- that would
    improve class separation but distort predicted probabilities away
    from the real ~4% base rate, which the calibration check relies on
    being honest.
    """
    x = train[MODEL_FEATURE_COLUMNS].to_numpy()
    y = train["clicked"].to_numpy()
    pipeline = Pipeline(
        [
            ("scale", StandardScaler()),
            ("logreg", LogisticRegression(max_iter=1000)),
        ]
    )
    pipeline.fit(x, y)
    return pipeline


def _evaluate(model: Pipeline, frame: pd.DataFrame) -> dict:
    pred = model.predict_proba(frame[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    return {
        "log_loss": float(log_loss(frame["clicked"], pred)),
        "auc": float(roc_auc_score(frame["clicked"], pred)),
    }


def main() -> None:
    train = load_ranking_frame(TRAIN_PATH)
    validation = load_ranking_frame(VALIDATION_PATH)

    model = train_ranking_model(train)

    logreg = model.named_steps["logreg"]
    report = {
        "model_features": MODEL_FEATURE_COLUMNS,
        "train": _evaluate(model, train),
        "validation": _evaluate(model, validation),
        "coefficients": dict(zip(MODEL_FEATURE_COLUMNS, logreg.coef_[0].tolist(), strict=True)),
        "intercept": float(logreg.intercept_[0]),
    }

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    TRAIN_REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
