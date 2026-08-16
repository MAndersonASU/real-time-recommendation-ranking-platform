from pathlib import Path

import pandas as pd

from recommender.data.schema import (
    BEHAVIORS_COLUMNS,
    NEWS_COLUMNS,
    validate_behaviors,
    validate_news,
)

# MIND's raw Time column has no timezone information anywhere in its
# documentation; parsed as naive, not assumed to be any particular zone.
TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def load_news(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        sep="\t",
        header=None,
        names=NEWS_COLUMNS,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
    )
    validate_news(df)
    return df


def load_behaviors(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        sep="\t",
        header=None,
        names=BEHAVIORS_COLUMNS,
        dtype={
            "impression_id": "int64",
            "user_id": str,
            "time": str,
            "history": str,
            "impressions": str,
        },
        keep_default_na=False,
        na_values=[""],
    )
    df["time"] = pd.to_datetime(df["time"], format=TIME_FORMAT)
    validate_behaviors(df)
    return df


def explode_impressions(behaviors: pd.DataFrame) -> pd.DataFrame:
    """One row per (impression, candidate item) pair, with its click label."""
    pairs = behaviors["impressions"].str.split().explode()
    split = pairs.str.rsplit("-", n=1, expand=True)
    split.columns = ["news_id", "clicked"]
    split["clicked"] = split["clicked"].astype("int8")
    return split.join(behaviors[["impression_id", "user_id", "time"]])
