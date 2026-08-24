import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from recommender.data.mind import explode_impressions

MAX_HISTORY = 20
CONTENT_DIM = 64
CONTENT_MAX_FEATURES = 20000
CONTENT_SEED = 42


def build_item_content_matrix(
    news: pd.DataFrame,
    content_dim: int = CONTENT_DIM,
    max_features: int = CONTENT_MAX_FEATURES,
    seed: int = CONTENT_SEED,
) -> np.ndarray:
    """A dense per-article content vector, one row per catalog item in
    `news` row order, from the article's own title and abstract.

    This exists because category and subcategory alone cannot tell two
    articles apart: the pair takes only 284 distinct values across
    51,282 items (`docs/faiss-index.md`), so an item tower built from
    them collapses the whole catalog into 284 distinct embeddings and
    retrieval can identify the right topic but never the right article
    within it. The title/abstract text is the per-article signal that
    was missing.

    TF-IDF reduced by `TruncatedSVD` rather than used raw: the sparse
    TF-IDF matrix has `max_features` columns, far too wide to feed a
    small embedding model, while the reduced form is dense, fixed-width,
    and cheap to index. Row-normalized so no single long article
    dominates the scale.

    Deterministic: `TruncatedSVD` uses a randomized solver, so it is
    seeded here for the same reason training is
    (`recommender.seed`) -- a retrained model must be reproducible.
    Content-derived rather than id-derived on purpose, so an article
    never seen during training still gets a real vector, preserving the
    item tower's cold-item behavior.
    """
    text = news["title"].fillna("") + " " + news["abstract"].fillna("")
    tfidf = TfidfVectorizer(max_features=max_features, stop_words="english").fit_transform(text)
    # n_components must stay below the feature count, which a tiny test
    # catalog can easily fall under.
    n_components = min(content_dim, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
    if n_components < 1:
        return np.zeros((len(news), content_dim), dtype=np.float32)
    reduced = TruncatedSVD(n_components=n_components, random_state=seed).fit_transform(tfidf)

    norms = np.linalg.norm(reduced, axis=1, keepdims=True)
    reduced = reduced / np.where(norms == 0.0, 1.0, norms)

    # Zero-padded out to a fixed width so the model's input dimension
    # never depends on how small a given catalog happens to be.
    out = np.zeros((len(news), content_dim), dtype=np.float32)
    out[:, :n_components] = reduced.astype(np.float32)
    return out


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
    behaviors: pd.DataFrame,
    item_vocab: dict,
    max_history: int = MAX_HISTORY,
    row_by_news_id: dict | None = None,
) -> tuple:
    """Per-impression, fixed-length (max_history,) arrays: category ids,
    subcategory ids, catalog row positions, and a 1/0 mask marking real
    (non-padding) positions. One row per impression_id, in behaviors' row
    order -- reused across every candidate item within that impression,
    not recomputed per item.

    The catalog row positions exist so a caller can look each history
    item's content vector up out of `build_item_content_matrix`'s matrix
    on demand. Storing the row index (one int per position) rather than
    the content vector itself keeps this array small: materializing
    (impressions x max_history x CONTENT_DIM) floats for a real split
    would run to hundreds of megabytes, while the gather is cheap to do
    per batch.
    """
    n = len(behaviors)
    cat = np.zeros((n, max_history), dtype=np.int64)
    subcat = np.zeros((n, max_history), dtype=np.int64)
    item_rows = np.zeros((n, max_history), dtype=np.int64)
    mask = np.zeros((n, max_history), dtype=np.float32)

    for row_idx, history_raw in enumerate(behaviors["history"].to_numpy()):
        if not isinstance(history_raw, str) or not history_raw:
            continue
        history_ids = history_raw.split()[-max_history:]
        for j, news_id in enumerate(history_ids):
            if news_id in item_vocab:
                cat[row_idx, j], subcat[row_idx, j] = item_vocab[news_id]
                mask[row_idx, j] = 1.0
                if row_by_news_id is not None:
                    item_rows[row_idx, j] = row_by_news_id.get(news_id, 0)

    impression_row = pd.Series(np.arange(n), index=behaviors["impression_id"].to_numpy())
    return cat, subcat, mask, item_rows, impression_row


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
