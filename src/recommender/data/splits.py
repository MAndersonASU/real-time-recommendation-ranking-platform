from itertools import pairwise

import pandas as pd


def time_aware_split(
    behaviors: pd.DataFrame, validation_days: int = 1
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a behaviors table into (train, validation) by a chronological
    cutoff — the last `validation_days` days become validation. Never a
    random shuffle: a shuffled split would let validation rows sit
    chronologically before train rows, leaking future information back.
    """
    cutoff = behaviors["time"].max().normalize() - pd.Timedelta(days=validation_days - 1)
    train = behaviors[behaviors["time"] < cutoff]
    validation = behaviors[behaviors["time"] >= cutoff]
    return train, validation


def assert_no_time_leakage(*ordered_splits: pd.DataFrame) -> None:
    """Raise if any split's time range overlaps with or precedes the split before it."""
    for earlier, later in pairwise(ordered_splits):
        if earlier["time"].max() >= later["time"].min():
            raise ValueError("time-aware split ordering violated: overlap or leakage detected")
