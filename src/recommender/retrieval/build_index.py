import json
from pathlib import Path

import faiss
import numpy as np
import torch

from recommender.evaluation.contract import load_catalog, load_split
from recommender.retrieval.content_artifact import load_item_content
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_history_arrays,
    build_item_vocab,
)
from recommender.retrieval.index import (
    build_exact_index,
    build_ivf_index,
    compute_catalog_embeddings,
    measure_recall_at_n,
    measure_search_latency,
)
from recommender.retrieval.model import TwoTowerModel
from recommender.retrieval.train import EMBEDDING_DIM, MODEL_PATH

EXACT_INDEX_PATH = Path("data/processed/mind_small/faiss_exact.index")
IVF_INDEX_PATH = Path("data/processed/mind_small/faiss_ivf.index")
INDEX_REPORT_PATH = Path("data/processed/mind_small/faiss_index_report.json")
NLIST = 256
TOP_N = 50
NUM_QUERY_USERS = 500


def load_trained_model(num_categories: int, num_subcategories: int) -> TwoTowerModel:
    model = TwoTowerModel(num_categories, num_subcategories, EMBEDDING_DIM)
    state = torch.load(MODEL_PATH, weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model


def build_query_embeddings(
    model: TwoTowerModel,
    item_vocab: dict,
    num_users: int,
    item_content: np.ndarray,
    row_by_news_id: dict,
) -> np.ndarray:
    validation = load_split("validation").head(num_users)
    cat, subcat, mask, hist_rows, _ = build_history_arrays(
        validation, item_vocab, row_by_news_id=row_by_news_id
    )
    with torch.no_grad():
        vectors = model.user_vector(
            torch.from_numpy(cat),
            torch.from_numpy(subcat),
            torch.from_numpy(mask),
            torch.from_numpy(item_content[hist_rows]),
        )
    return vectors.numpy().astype(np.float32)


def main() -> None:
    news = load_catalog()
    item_vocab, categories, subcategories = build_item_vocab(news)
    catalog_cat, catalog_subcat, row_by_news_id = build_catalog_arrays(news, item_vocab)
    item_content = load_item_content(news)

    model = load_trained_model(len(categories) + 1, len(subcategories) + 1)
    catalog_embeddings = compute_catalog_embeddings(
        model, catalog_cat, catalog_subcat, item_content
    )
    print(f"catalog embeddings: {catalog_embeddings.shape}")

    exact_index = build_exact_index(catalog_embeddings)
    ivf_index = build_ivf_index(catalog_embeddings, nlist=NLIST, nprobe=8)
    faiss.write_index(exact_index, str(EXACT_INDEX_PATH))
    faiss.write_index(ivf_index, str(IVF_INDEX_PATH))

    queries = build_query_embeddings(
        model, item_vocab, NUM_QUERY_USERS, item_content, row_by_news_id
    )
    print(f"query embeddings: {queries.shape}")

    recall_by_nprobe = {}
    latency_by_nprobe = {}
    for nprobe in (1, 8, 32, NLIST):
        ivf_index.nprobe = nprobe
        recall_by_nprobe[nprobe] = measure_recall_at_n(exact_index, ivf_index, queries, TOP_N)
        latency_by_nprobe[nprobe] = measure_search_latency(ivf_index, queries, TOP_N)

    exact_latency = measure_search_latency(exact_index, queries, TOP_N)

    report = {
        "catalog_size": len(news),
        "embedding_dim": EMBEDDING_DIM,
        "nlist": NLIST,
        "top_n": TOP_N,
        "num_query_users": len(queries),
        "exact_search_seconds_per_query": exact_latency,
        "recall_at_n_vs_exact_by_nprobe": recall_by_nprobe,
        "ivf_seconds_per_query_by_nprobe": latency_by_nprobe,
    }
    INDEX_REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
