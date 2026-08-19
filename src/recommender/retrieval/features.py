import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions

MAX_HISTORY = 20


def build_item_vocab(news: pd.DataFrame) -> dict:
    """news_id -> (category_idx, subcategory_idx). Index 0 is reserved as a
    padding/unknown filler for both vocabularies -- its embedding is always
    masked out wherever it's used, never trained toward meaning anything.
    """
    categories = {c: i + 1 for i, c in enumerate(sorted(news["category"].unique()))}
    subcategories = {s: i + 1 for i, s in enumerate(sorted(news["subcategory"].unique()))}

    item_vocab = {
        row.news_id: (categories[row.category], subcategories[row.subcategory])
        for row in news.itertuples()
    }
    return item_vocab, categories, subcategories


def build_history_arrays(
    behaviors: pd.DataFrame, item_vocab: dict, max_history: int = MAX_HISTORY
) -> tuple:
    """Per-impression, fixed-length (max_history,) arrays: category ids,
    subcategory ids, and a 1/0 mask marking real (non-padding) positions.
    One row per impression_id, in behaviors' row order -- reused across
    every candidate item within that impression, not recomputed per item.
    """
    n = len(behaviors)
    cat = np.zeros((n, max_history), dtype=np.int64)
    subcat = np.zeros((n, max_history), dtype=np.int64)
    mask = np.zeros((n, max_history), dtype=np.float32)

    for row_idx, history_raw in enumerate(behaviors["history"].to_numpy()):
        if not isinstance(history_raw, str) or not history_raw:
            continue
        history_ids = history_raw.split()[-max_history:]
        for j, news_id in enumerate(history_ids):
            if news_id in item_vocab:
                cat[row_idx, j], subcat[row_idx, j] = item_vocab[news_id]
                mask[row_idx, j] = 1.0

    impression_row = pd.Series(np.arange(n), index=behaviors["impression_id"].to_numpy())
    return cat, subcat, mask, impression_row


def build_catalog_arrays(news: pd.DataFrame, item_vocab: dict) -> tuple:
    """Parallel (category_idx, subcategory_idx) arrays, one row per
    catalog item, in the same row order as `news`. Sampling a random
    negative is then just drawing a row index uniformly and indexing
    directly, with no news_id round-trip.
    """
    news_ids = news["news_id"].to_numpy()
    cat = np.array([item_vocab[nid][0] for nid in news_ids], dtype=np.int64)
    subcat = np.array([item_vocab[nid][1] for nid in news_ids], dtype=np.int64)
    row_by_news_id = {nid: i for i, nid in enumerate(news_ids)}
    return cat, subcat, row_by_news_id


def build_user_clicked_rows(behaviors: pd.DataFrame, row_by_news_id: dict) -> dict:
    """user_id -> set of catalog row positions this user actually clicked
    anywhere in this split. Used only to keep sampled negatives honest --
    never sample an item this user is known to like as a "negative".
    Built exclusively from the given split (train, in practice): using
    validation or replay clicks here would leak evaluation-time
    information into what training treats as a legitimate negative.
    """
    exploded = explode_impressions(behaviors)
    clicks = exploded[exploded["clicked"] == 1]
    result: dict = {}
    for user_id, group in clicks.groupby("user_id"):
        result[user_id] = {row_by_news_id[nid] for nid in group["news_id"] if nid in row_by_news_id}
    return result
