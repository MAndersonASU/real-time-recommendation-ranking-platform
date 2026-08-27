import numpy as np

from recommender.evaluation.metrics import dcg_at_k


def recall_at_n_known_total(relevance: np.ndarray, true_relevant_count: int, n: int) -> float:
    """recall_at_k (metrics.py) infers "total relevant" from the passed
    array itself -- correct only when that array is the complete
    candidate set, as it was for every baseline evaluation. Retrieval's
    relevance array is only a top-N slice of the full catalog, so a real
    click missing from that slice would be invisible to it. This version
    takes the true click count as an explicit, independently-looked-up
    argument instead of inferring it from what was retrieved.
    """
    if true_relevant_count == 0:
        return 0.0
    return float(relevance[:n].sum() / true_relevant_count)


def ndcg_at_n_known_total(relevance: np.ndarray, true_relevant_count: int, n: int) -> float:
    """Same correction applied to NDCG: the "ideal" ranking is built from
    the true relevant count (capped at n), not from sorting whatever
    happened to be in the retrieved slice -- otherwise a slice missing
    real clicks would understate what a perfect retrieval could have
    achieved, inflating the reported score.
    """
    dcg = dcg_at_k(relevance, n)
    ideal = np.zeros(n)
    ideal[: min(true_relevant_count, n)] = 1
    idcg = dcg_at_k(ideal, n)
    if idcg == 0:
        return 0.0
    return dcg / idcg
