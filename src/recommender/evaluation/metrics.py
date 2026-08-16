import numpy as np


def hit_rate_at_k(relevance: np.ndarray, k: int) -> float:
    return float(np.any(relevance[:k] > 0))


def recall_at_k(relevance: np.ndarray, k: int) -> float:
    total_relevant = relevance.sum()
    if total_relevant == 0:
        return 0.0
    return float(relevance[:k].sum() / total_relevant)


def dcg_at_k(relevance: np.ndarray, k: int) -> float:
    relevance = relevance[:k]
    discounts = np.log2(np.arange(2, len(relevance) + 2))
    return float(np.sum(relevance / discounts))


def ndcg_at_k(relevance: np.ndarray, k: int) -> float:
    ideal = np.sort(relevance)[::-1]
    idcg = dcg_at_k(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg_at_k(relevance, k) / idcg


def reciprocal_rank(relevance: np.ndarray) -> float:
    hits = np.nonzero(relevance)[0]
    if len(hits) == 0:
        return 0.0
    return float(1.0 / (hits[0] + 1))


def catalog_coverage(recommended_item_ids: set, catalog_size: int) -> float:
    if catalog_size == 0:
        return 0.0
    return len(recommended_item_ids) / catalog_size
