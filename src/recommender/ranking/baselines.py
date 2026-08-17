import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

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


def build_content_vectors(news: pd.DataFrame, max_features: int = 5000):
    """TF-IDF vectors (title + abstract) for every article, and a lookup
    from news_id to that article's row in the returned sparse matrix.
    """
    text = news["title"].fillna("") + " " + news["abstract"].fillna("")
    vectorizer = TfidfVectorizer(max_features=max_features, stop_words="english")
    vectors = vectorizer.fit_transform(text)
    row_by_id = {news_id: i for i, news_id in enumerate(news["news_id"])}
    return vectors, row_by_id


def rank_by_content_similarity(
    exploded_impression: pd.DataFrame,
    history_ids: list,
    vectors,
    row_by_id: dict,
    popularity: pd.Series,
) -> pd.DataFrame:
    """Order one impression's candidates by cosine similarity to the
    user's content profile — the mean TF-IDF vector of their history.
    Falls back to rank_by_popularity when there's no usable history.
    """
    history_rows = [row_by_id[nid] for nid in history_ids if nid in row_by_id]
    if not history_rows:
        return rank_by_popularity(exploded_impression, popularity)

    profile = np.asarray(vectors[history_rows].mean(axis=0)).ravel()
    norm = np.linalg.norm(profile)
    if norm > 0:
        profile = profile / norm

    candidate_rows = [row_by_id[nid] for nid in exploded_impression["news_id"]]
    similarity = np.asarray(vectors[candidate_rows] @ profile).ravel()

    scored = exploded_impression.assign(similarity=similarity)
    return scored.sort_values(["similarity", "news_id"], ascending=[False, True])
