import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.decomposition import TruncatedSVD
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


def build_collaborative_factors(behaviors: pd.DataFrame, n_components: int = 20, random_state: int = 42):
    """Factorize the training click matrix (users x items) into a small
    number of latent factors per user and per item via TruncatedSVD.
    """
    clicks = explode_impressions(behaviors)
    clicks = clicks[clicks["clicked"] == 1]

    users = clicks["user_id"].astype("category")
    items = clicks["news_id"].astype("category")

    matrix = sp.csr_matrix(
        (np.ones(len(clicks)), (users.cat.codes, items.cat.codes)),
        shape=(len(users.cat.categories), len(items.cat.categories)),
    )

    svd = TruncatedSVD(n_components=n_components, random_state=random_state)
    user_factors = svd.fit_transform(matrix)
    item_factors = svd.components_.T

    user_row_by_id = {uid: i for i, uid in enumerate(users.cat.categories)}
    item_row_by_id = {iid: i for i, iid in enumerate(items.cat.categories)}
    return user_factors, item_factors, user_row_by_id, item_row_by_id


def rank_by_collaborative_filtering(
    exploded_impression: pd.DataFrame,
    user_id: str,
    user_factors: np.ndarray,
    item_factors: np.ndarray,
    user_row_by_id: dict,
    item_row_by_id: dict,
    popularity: pd.Series,
) -> pd.DataFrame:
    """Order one impression's candidates by predicted user-item affinity
    (dot product of latent factors). Falls back to rank_by_popularity when
    the user has no training click history at all. A candidate item never
    clicked during training scores -inf, not 0 — a raw dot product isn't
    bounded at zero the way cosine similarity was, so 0 would misrepresent
    "no signal" as "average affinity."
    """
    if user_id not in user_row_by_id:
        return rank_by_popularity(exploded_impression, popularity)

    user_vector = user_factors[user_row_by_id[user_id]]
    scores = np.array(
        [
            float(user_vector @ item_factors[item_row_by_id[nid]])
            if nid in item_row_by_id
            else -np.inf
            for nid in exploded_impression["news_id"]
        ]
    )

    scored = exploded_impression.assign(cf_score=scores)
    return scored.sort_values(["cf_score", "news_id"], ascending=[False, True])
