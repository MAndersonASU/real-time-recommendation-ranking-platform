import pandas as pd

# Chosen from real measurement (docs/reranking-diversity.md), not guessed:
# 53.1% of naive top-10 slates already carry 4+ items from a single
# category on the real validation set, so a cap of 3 changes a majority of
# slates. Near-duplicate content similarity above 0.5 covers only ~0.25%
# of within-slate pairs -- a real but much rarer safeguard, not the main
# lever this policy relies on.
DEFAULT_MAX_PER_CATEGORY = 3
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.5


def build_diverse_slate(
    candidates: pd.DataFrame,
    score_column: str,
    k: int,
    category_by_id: pd.Series,
    tfidf_vectors,
    tfidf_row_by_id: dict,
    max_per_category: int = DEFAULT_MAX_PER_CATEGORY,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> pd.DataFrame:
    """Greedily builds a k-item slate in descending `score_column` order,
    skipping a candidate that would exceed `max_per_category` for its
    category or that is a near-duplicate (TF-IDF cosine similarity at or
    above `near_duplicate_threshold`) of an already-selected item. A
    second, unconstrained pass fills any remaining slots by score alone --
    a slate short of k items is worse than a slightly less diverse full
    one, so constraints never reduce slate size, only reorder it.
    """
    ordered = candidates.sort_values([score_column, "news_id"], ascending=[False, True])

    selected_ids: list = []
    selected_set: set = set()
    category_counts: dict = {}

    def is_near_duplicate(news_id: str) -> bool:
        if news_id not in tfidf_row_by_id or not selected_ids:
            return False
        candidate_row = tfidf_vectors[tfidf_row_by_id[news_id]]
        for selected_id in selected_ids:
            if selected_id not in tfidf_row_by_id:
                continue
            selected_row = tfidf_vectors[tfidf_row_by_id[selected_id]]
            similarity = float(candidate_row.multiply(selected_row).sum())
            if similarity >= near_duplicate_threshold:
                return True
        return False

    for news_id in ordered["news_id"]:
        if len(selected_ids) >= k:
            break
        category = category_by_id.get(news_id)
        if category is not None and category_counts.get(category, 0) >= max_per_category:
            continue
        if is_near_duplicate(news_id):
            continue
        selected_ids.append(news_id)
        selected_set.add(news_id)
        category_counts[category] = category_counts.get(category, 0) + 1

    if len(selected_ids) < k:
        for news_id in ordered["news_id"]:
            if len(selected_ids) >= k:
                break
            if news_id in selected_set:
                continue
            selected_ids.append(news_id)
            selected_set.add(news_id)

    return ordered.set_index("news_id").loc[selected_ids].reset_index()
