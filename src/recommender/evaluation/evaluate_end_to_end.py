import json
from pathlib import Path

import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import TOP_K, load_split
from recommender.evaluation.metrics import hit_rate_at_k, reciprocal_rank
from recommender.evaluation.retrieval_metrics import ndcg_at_n_known_total, recall_at_n_known_total
from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext

REPORT_PATH = Path("data/processed/mind_small/end_to_end_evaluation_report.json")
DEFAULT_NUM_IMPRESSIONS = 500


def evaluate_end_to_end(
    context: ServingContext,
    num_impressions: int = DEFAULT_NUM_IMPRESSIONS,
    k: int = TOP_K,
    validation: pd.DataFrame | None = None,
) -> dict:
    """A real, deployment-representative evaluation, deliberately
    reported alongside -- never in place of -- the frozen-protocol
    numbers in `docs/ranking-evaluation.md`. Those numbers score the
    ranking model against MIND's own impression candidate list (a
    disclosed, deliberate choice, `docs/ranking-features.md`, made to
    isolate "does the ranking model help" from "is the current
    retrieval implementation's candidate generation good enough" --
    RQ2 vs RQ1). That choice is real and still valid for what it
    measures, but it does mean those numbers alone don't say anything
    about the real, deployed candidate distribution the live pipeline
    actually ranks. This function does: it calls the real
    `recommend()` pipeline (retrieval -> ranking -> reranking, `safe_
    recommend`, exactly what `/recommend` runs) for real validation
    users and checks whether their real recorded click ends up in the
    real returned slate -- the full pipeline, the real Faiss-retrieved
    candidates, not MIND's own pre-built impression list.
    """
    validation = validation if validation is not None else load_split("validation")
    exploded = explode_impressions(validation.head(num_impressions))

    hit_rates: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []
    reciprocal_ranks: list[float] = []
    impressions_with_clicks = 0
    fallback_count = 0

    for _impression_id, group in exploded.groupby("impression_id", sort=False):
        clicked_ids = set(group.loc[group["clicked"] == 1, "news_id"])
        if not clicked_ids:
            continue
        impressions_with_clicks += 1
        true_relevant_count = len(clicked_ids)

        user_id = group["user_id"].iloc[0]
        request_time = group["time"].iloc[0]
        request = RecommendationRequest(user_id=user_id, num_candidates=k, request_time=request_time)

        fell_back = {"value": False}

        def _mark_fallback(container=fell_back) -> None:
            container["value"] = True

        response = safe_recommend(request, context, on_fallback=_mark_fallback)
        if fell_back["value"]:
            fallback_count += 1

        recommended_ids = [item.news_id for item in response.recommendations]
        relevance = np.array([1 if nid in clicked_ids else 0 for nid in recommended_ids])

        hit_rates.append(hit_rate_at_k(relevance, k))
        recalls.append(recall_at_n_known_total(relevance, true_relevant_count, k))
        ndcgs.append(ndcg_at_n_known_total(relevance, true_relevant_count, k))
        reciprocal_ranks.append(reciprocal_rank(relevance))

    return {
        "is_end_to_end_not_the_frozen_impression_list_protocol": True,
        "k": k,
        "impressions_sampled": num_impressions,
        "impressions_with_a_real_click": impressions_with_clicks,
        "fallback_count": fallback_count,
        "hit_rate_at_k": float(np.mean(hit_rates)) if hit_rates else 0.0,
        "recall_at_k": float(np.mean(recalls)) if recalls else 0.0,
        "ndcg_at_k": float(np.mean(ndcgs)) if ndcgs else 0.0,
        "mrr": float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0,
    }


def main() -> None:
    from recommender.serving.pipeline import build_serving_context

    context = build_serving_context()
    report = evaluate_end_to_end(context)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
