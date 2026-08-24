import time

import faiss
import numpy as np
import torch

from recommender.retrieval.model import TwoTowerModel


def compute_catalog_embeddings(
    model: TwoTowerModel,
    catalog_category: np.ndarray,
    catalog_subcategory: np.ndarray,
    catalog_content: np.ndarray,
) -> np.ndarray:
    """Run every catalog item through the trained item tower once. No
    training, no gradient -- just producing a fixed embedding per item.
    """
    model.eval()
    with torch.no_grad():
        vectors = model.item_vector(
            torch.from_numpy(catalog_category),
            torch.from_numpy(catalog_subcategory),
            torch.from_numpy(catalog_content),
        )
    return vectors.numpy().astype(np.float32)


def build_exact_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def build_ivf_index(embeddings: np.ndarray, nlist: int, nprobe: int = 8) -> faiss.IndexIVFFlat:
    dim = embeddings.shape[1]
    quantizer = faiss.IndexFlatIP(dim)
    index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
    index.train(embeddings)
    index.add(embeddings)
    index.nprobe = nprobe
    return index


def measure_recall_at_n(
    exact_index: faiss.IndexFlatIP, approx_index: faiss.IndexIVFFlat, queries: np.ndarray, n: int
) -> float:
    """Fraction of the exact index's true top-N neighbors that the
    approximate index also returns, averaged over all queries.
    """
    _, exact_ids = exact_index.search(queries, n)
    _, approx_ids = approx_index.search(queries, n)

    overlaps = []
    for exact_row, approx_row in zip(exact_ids, approx_ids, strict=True):
        overlaps.append(len(set(exact_row) & set(approx_row)) / n)
    return float(np.mean(overlaps))


def measure_search_latency(index, queries: np.ndarray, n: int, repeats: int = 5) -> float:
    """Mean seconds per query, averaged over `repeats` full passes over
    `queries` (a batched call each time, matching real usage).
    """
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        index.search(queries, n)
        timings.append((time.perf_counter() - start) / len(queries))
    return float(np.mean(timings))
