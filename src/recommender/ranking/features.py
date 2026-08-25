import numpy as np
import pandas as pd
import torch

from recommender.data.mind import explode_impressions
from recommender.ranking.baselines import build_content_vectors, compute_popularity
from recommender.retrieval.content_artifact import load_item_content
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_history_arrays,
    build_item_vocab,
)
from recommender.retrieval.model import TwoTowerModel

FEATURE_COLUMNS = [
    "retrieval_score",
    "popularity",
    "category_match",
    "content_similarity",
    "user_history_length",
    "hour_of_day",
]


def hour_of_day(timestamp) -> int:
    """The single definition of `hour_of_day`, used by both offline
    feature building and the serving path.

    **Timezone convention, stated because it is not derivable from the
    data.** MIND does not document the timezone of its timestamps, and
    this project has not established it. The hour is therefore taken
    verbatim from the timestamp as given: for historical rows that means
    dataset-local time, whatever zone that is.

    The consequence is a real, disclosed parity gap. A live request with
    no historical anchor falls back to the UTC wall clock, so its
    `hour_of_day` is a UTC hour while every trained value was a
    dataset-local hour. Both paths call this one function, so they cannot
    drift in *derivation* -- but the underlying zones still differ, and
    no amount of shared code fixes that.

    Removing the feature outright would close the gap; it is kept because
    it carries the smallest coefficient in the trained model and removing
    it would invalidate every published number for a marginal input. That
    tradeoff is recorded rather than hidden (`docs/feature-parity.md`).
    """
    stamp = pd.Timestamp(timestamp)
    return int(stamp.hour)


def build_feature_context(
    train: pd.DataFrame,
    news: pd.DataFrame,
    model: TwoTowerModel,
    item_content: np.ndarray | None = None,
) -> dict:
    """Everything derived once from train + catalog + a trained two-tower
    model, reused across every row a caller builds features for. Separated
    from build_ranking_rows so train and validation feature-building share
    one fitted popularity count, one fitted TF-IDF vocabulary, and one
    catalog embedding matrix instead of refitting them per split.
    """
    item_vocab, _categories, _subcategories = build_item_vocab(news)
    catalog_cat, catalog_subcat, row_by_news_id = build_catalog_arrays(news, item_vocab)
    # Loaded from the persisted artifact by default, so the ranking
    # features are built in the same coordinate system the retrieval
    # model was trained in. Injectable so a caller that already holds
    # the matrix -- or a test working on a synthetic catalog with no
    # persisted artifact -- can supply it directly.
    item_content = item_content if item_content is not None else load_item_content(news)

    model.eval()
    with torch.no_grad():
        catalog_embeddings = model.item_vector(
            torch.from_numpy(catalog_cat),
            torch.from_numpy(catalog_subcat),
            torch.from_numpy(item_content),
        ).numpy()

    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)

    return {
        "item_vocab": item_vocab,
        "item_content": item_content,
        "model": model,
        "catalog_embeddings": catalog_embeddings,
        "row_by_news_id": row_by_news_id,
        "popularity": compute_popularity(train),
        "tfidf_vectors": tfidf_vectors,
        "tfidf_row_by_id": tfidf_row_by_id,
        "category_by_id": news.set_index("news_id")["category"],
    }


def history_ids_from_raw(history_raw) -> list:
    return history_raw.split() if isinstance(history_raw, str) and history_raw else []


def dominant_category(history_ids: list, category_by_id: pd.Series):
    """The single most common category among a user's history items, or
    None if the user has no usable history -- distinguishing "no signal"
    from "matches nothing" the same way rank_by_content_similarity falls
    back explicitly rather than silently scoring everything zero.
    """
    cats = [category_by_id[nid] for nid in history_ids if nid in category_by_id.index]
    if not cats:
        return None
    return pd.Series(cats).mode().iloc[0]


def content_profile(history_ids: list, tfidf_vectors, tfidf_row_by_id: dict):
    rows = [tfidf_row_by_id[nid] for nid in history_ids if nid in tfidf_row_by_id]
    if not rows:
        return None
    profile = np.asarray(tfidf_vectors[rows].mean(axis=0)).ravel()
    norm = np.linalg.norm(profile)
    return profile / norm if norm > 0 else profile


def build_ranking_rows(behaviors: pd.DataFrame, context: dict) -> pd.DataFrame:
    """One row per (impression, candidate) pair -- the same population
    evaluate_baseline.py scores -- each carrying the six ranking features
    plus the click label. Every feature is computed only from `behaviors`'
    own history/time fields and from train-fitted context, never from a
    later impression, so nothing here can see the future.
    """
    item_vocab = context["item_vocab"]
    catalog_embeddings = context["catalog_embeddings"]
    row_by_news_id = context["row_by_news_id"]
    popularity = context["popularity"]
    tfidf_vectors = context["tfidf_vectors"]
    tfidf_row_by_id = context["tfidf_row_by_id"]
    category_by_id = context["category_by_id"]

    hist_cat, hist_subcat, hist_mask, hist_rows, impression_row = build_history_arrays(
        behaviors, item_vocab, row_by_news_id=row_by_news_id
    )
    item_content = context["item_content"]
    with torch.no_grad():
        user_embeddings = context["model"].user_vector(
            torch.from_numpy(hist_cat),
            torch.from_numpy(hist_subcat),
            torch.from_numpy(hist_mask),
            torch.from_numpy(item_content[hist_rows]),
        ).numpy()

    history_by_impression = behaviors.set_index("impression_id")["history"]
    impression_time_by_id = behaviors.set_index("impression_id")["time"]
    exploded = explode_impressions(behaviors)

    frames = []
    for impression_id, group in exploded.groupby("impression_id", sort=False):
        history_ids = history_ids_from_raw(history_by_impression.loc[impression_id])
        user_emb = user_embeddings[impression_row.loc[impression_id]]
        user_dominant_category = dominant_category(history_ids, category_by_id)
        profile = content_profile(history_ids, tfidf_vectors, tfidf_row_by_id)

        news_ids = group["news_id"].to_numpy()
        item_rows = np.array([row_by_news_id[nid] for nid in news_ids])
        retrieval_scores = catalog_embeddings[item_rows] @ user_emb
        pops = np.log1p(np.array([popularity.get(nid, 0) for nid in news_ids], dtype=np.float64))
        cats = np.array([category_by_id[nid] for nid in news_ids])
        category_matches = (
            (cats == user_dominant_category).astype(float)
            if user_dominant_category is not None
            else np.zeros(len(news_ids))
        )
        if profile is not None:
            tfidf_rows = np.array([tfidf_row_by_id[nid] for nid in news_ids])
            content_sims = np.asarray(tfidf_vectors[tfidf_rows] @ profile).ravel()
        else:
            content_sims = np.zeros(len(news_ids))

        frames.append(
            pd.DataFrame(
                {
                    "impression_id": impression_id,
                    "news_id": news_ids,
                    "clicked": group["clicked"].to_numpy(),
                    "retrieval_score": retrieval_scores,
                    "popularity": pops,
                    "category_match": category_matches,
                    "content_similarity": content_sims,
                    "user_history_length": len(history_ids),
                    "hour_of_day": hour_of_day(impression_time_by_id.loc[impression_id]),
                }
            )
        )

    return pd.concat(frames, ignore_index=True)
