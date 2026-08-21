import numpy as np
import pandas as pd


def calibration_bins(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Equal-frequency bins of predicted probability, each with its mean
    predicted probability, observed click rate, and row count -- the
    standard reliability-diagram breakdown. Equal-frequency rather than
    equal-width, since click probabilities cluster into a narrow range
    near the base rate; equal-width bins would leave most of them empty.
    """
    frame = pd.DataFrame({"y_true": np.asarray(y_true), "y_pred": np.asarray(y_pred)})
    frame["bin"] = pd.qcut(frame["y_pred"], q=n_bins, duplicates="drop")
    grouped = frame.groupby("bin", observed=True).agg(
        mean_predicted=("y_pred", "mean"),
        observed_rate=("y_true", "mean"),
        count=("y_true", "size"),
    )
    return grouped.reset_index(drop=True)


def expected_calibration_error(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> float:
    """Size-weighted average gap between each bin's mean predicted
    probability and its actual observed click rate -- a single number
    summarizing the calibration table above.
    """
    bins = calibration_bins(y_true, y_pred, n_bins)
    total = bins["count"].sum()
    gaps = (bins["mean_predicted"] - bins["observed_rate"]).abs()
    return float((bins["count"] / total * gaps).sum())
