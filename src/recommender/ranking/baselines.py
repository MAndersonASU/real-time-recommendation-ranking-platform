import pandas as pd

from recommender.data.mind import explode_impressions


def compute_popularity(behaviors: pd.DataFrame) -> pd.Series:
    """Click count per item, computed only from the given (training) split."""
    exploded = explode_impressions(behaviors)
    return exploded.groupby("news_id")["clicked"].sum()


def rank_by_popularity(exploded_impression: pd.DataFrame, popularity: pd.Series) -> pd.DataFrame:
    """Order one impression's exploded (news_id, clicked) rows by descending
    training-set popularity. Items never seen in training default to 0.
    Ties break by news_id so the ordering is fully deterministic.
    """
    scored = exploded_impression.assign(
        popularity=exploded_impression["news_id"].map(popularity).fillna(0)
    )
    return scored.sort_values(["popularity", "news_id"], ascending=[False, True])
