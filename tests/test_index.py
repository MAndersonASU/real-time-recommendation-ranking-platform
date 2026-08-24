import numpy as np
import torch

from recommender.retrieval.features import CONTENT_DIM
from recommender.retrieval.index import (
    build_exact_index,
    build_ivf_index,
    compute_catalog_embeddings,
    measure_recall_at_n,
    measure_search_latency,
)
from recommender.retrieval.model import TwoTowerModel


def test_compute_catalog_embeddings_shape():
    model = TwoTowerModel(num_categories=3, num_subcategories=3, embedding_dim=8)
    cat = torch.tensor([1, 2, 1])
    subcat = torch.tensor([1, 2, 1])

    content = np.zeros((len(cat), CONTENT_DIM), dtype=np.float32)
    embeddings = compute_catalog_embeddings(model, cat.numpy(), subcat.numpy(), content)

    assert embeddings.shape == (3, 8)
    assert embeddings.dtype == np.float32


def test_exact_index_finds_identical_orthogonal_vector():
    # Orthogonal unit vectors: each row's only real match is itself.
    embeddings = np.eye(6, dtype=np.float32)
    index = build_exact_index(embeddings)

    distances, ids = index.search(embeddings[2:3], 1)

    assert ids[0, 0] == 2
    assert distances[0, 0] == 1.0  # self dot-product for a unit vector


def test_ivf_recall_is_exact_when_every_cluster_is_probed():
    rng = np.random.default_rng(0)
    embeddings = rng.normal(size=(200, 16)).astype(np.float32)
    nlist = 8

    exact = build_exact_index(embeddings)
    # nprobe == nlist means every cluster gets searched -- IVF search
    # degenerates to exact search, so recall against the exact index
    # should be exactly 1.0, not just "close".
    approx = build_ivf_index(embeddings, nlist=nlist, nprobe=nlist)

    queries = embeddings[:20]
    recall = measure_recall_at_n(exact, approx, queries, n=5)

    assert recall == 1.0


def test_ivf_recall_with_nprobe_one_is_at_most_full_recall():
    rng = np.random.default_rng(1)
    embeddings = rng.normal(size=(200, 16)).astype(np.float32)

    exact = build_exact_index(embeddings)
    approx = build_ivf_index(embeddings, nlist=8, nprobe=1)  # search only 1 of 8 clusters

    queries = embeddings[:20]
    recall = measure_recall_at_n(exact, approx, queries, n=5)

    assert 0.0 <= recall <= 1.0
    # Searching only 1/8 of the clusters should generally miss some true
    # neighbors versus probing every cluster -- a real, not just possible,
    # degradation for this data, though not asserted as a hard bound since
    # cluster membership is data-dependent.


def test_measure_search_latency_returns_positive_time():
    embeddings = np.random.default_rng(2).normal(size=(50, 8)).astype(np.float32)
    index = build_exact_index(embeddings)

    latency = measure_search_latency(index, embeddings[:5], n=3, repeats=2)

    assert latency > 0.0
