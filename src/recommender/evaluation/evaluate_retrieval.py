import json
from pathlib import Path

import numpy as np
import torch

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import load_catalog, load_split
from recommender.evaluation.metrics import catalog_coverage, hit_rate_at_k, reciprocal_rank
from recommender.evaluation.retrieval_metrics import ndcg_at_n_known_total, recall_at_n_known_total
from recommender.retrieval.build_index import load_trained_model
from recommender.retrieval.content_artifact import load_item_content
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_history_arrays,
    build_item_vocab,
)
from recommender.retrieval.index import build_exact_index, compute_catalog_embeddings

RETRIEVAL_REPORT_PATH = Path("data/processed/mind_small/retrieval_evaluation_report.json")
N = 100  # retrieval-stage candidate count -- distinct from K=10, per docs/research-scenario.md


def evaluate_retrieval(n: int = N) -> dict:
    validation = load_split("validation")
    news = load_catalog()
    item_vocab, categories, subcategories = build_item_vocab(news)
    catalog_cat, catalog_subcat, row_by_news_id = build_catalog_arrays(news, item_vocab)
    item_content = load_item_content(news)
    news_ids = news["news_id"].to_numpy()

    model = load_trained_model(len(categories) + 1, len(subcategories) + 1)
    catalog_embeddings = compute_catalog_embeddings(
        model, catalog_cat, catalog_subcat, item_content
    )
    # Exact search, deliberately: isolates embedding quality from the
    # approximate index's already-measured accuracy cost (docs/archive/faiss-index.md).
    index = build_exact_index(catalog_embeddings)

    hist_cat, hist_subcat, hist_mask, hist_rows, _ = build_history_arrays(
        validation, item_vocab, row_by_news_id=row_by_news_id
    )
    with torch.no_grad():
        user_embeddings = model.user_vector(
            torch.from_numpy(hist_cat),
            torch.from_numpy(hist_subcat),
            torch.from_numpy(hist_mask),
            torch.from_numpy(item_content[hist_rows]),
        )
    user_embeddings = user_embeddings.numpy().astype(np.float32)

    _, retrieved_rows = index.search(user_embeddings, n)

    exploded = explode_impressions(validation)
    clicked_by_impression = exploded[exploded["clicked"] == 1].groupby("impression_id")[
        "news_id"
    ].apply(set)

    hit_rates, recalls, ndcgs, rrs = [], [], [], []
    recommended_items: set = set()

    for i, impression_id in enumerate(validation["impression_id"].to_numpy()):
        clicked = clicked_by_impression.get(impression_id, set())
        retrieved_news_ids = news_ids[retrieved_rows[i]]
        relevance = np.array([1 if nid in clicked else 0 for nid in retrieved_news_ids])

        hit_rates.append(hit_rate_at_k(relevance, n))
        recalls.append(recall_at_n_known_total(relevance, len(clicked), n))
        ndcgs.append(ndcg_at_n_known_total(relevance, len(clicked), n))
        rrs.append(reciprocal_rank(relevance))
        recommended_items.update(retrieved_news_ids)

    return {
        "model": "two_tower_retrieval",
        "n": n,
        "impressions_evaluated": len(validation),
        "hit_rate_at_n": float(np.mean(hit_rates)),
        "recall_at_n": float(np.mean(recalls)),
        "ndcg_at_n": float(np.mean(ndcgs)),
        "mrr": float(np.mean(rrs)),
        "catalog_coverage_at_n": catalog_coverage(recommended_items, len(news)),
        "catalog_size": len(news),
        "distinct_items_recommended": len(recommended_items),
    }


def main() -> None:
    from recommender.evaluation.publish import publish_retrieval_report

    report = evaluate_retrieval()
    RETRIEVAL_REPORT_PATH.write_text(json.dumps(report, indent=2))
    # Published by the run that measured, so the recorded commit and
    # artifact fingerprints describe these numbers rather than whatever
    # happened to be checked out at some later publishing step.
    published = publish_retrieval_report(report)
    print(json.dumps(report, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
