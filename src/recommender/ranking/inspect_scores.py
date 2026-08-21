import json
from pathlib import Path

import joblib
import pandas as pd

from recommender.ranking.build_dataset import VALIDATION_PATH
from recommender.ranking.calibration import calibration_bins, expected_calibration_error
from recommender.ranking.train import MODEL_FEATURE_COLUMNS, MODEL_PATH

INSPECTION_REPORT_PATH = Path("data/processed/mind_small/ranking_calibration_report.json")


def inspect_scores() -> dict:
    model = joblib.load(MODEL_PATH)
    validation = pd.read_parquet(VALIDATION_PATH)

    pred = model.predict_proba(validation[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    y_true = validation["clicked"].to_numpy()
    bins = calibration_bins(y_true, pred, n_bins=10)

    return {
        "expected_calibration_error": expected_calibration_error(y_true, pred, n_bins=10),
        "calibration_bins": bins.to_dict(orient="records"),
        "score_distribution": {
            "mean": float(pred.mean()),
            "std": float(pred.std()),
            "min": float(pred.min()),
            "max": float(pred.max()),
        },
        "feature_correlations": validation[MODEL_FEATURE_COLUMNS].corr().round(4).to_dict(),
    }


def main() -> None:
    report = inspect_scores()
    INSPECTION_REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
