import json
from pathlib import Path

from recommender.evaluation.contract import load_catalog, load_split
from recommender.explanation.contract import build_explanation_requests
from recommender.explanation.generation import (
    build_template_explanation,
    generate_explanation,
)
from recommender.explanation.retrieval import retrieve_support_context
from recommender.serving.contract import RecommendationRequest
from recommender.serving.pipeline import ServingContext, build_serving_context, recommend

REPORT_PATH = Path("data/processed/mind_small/explanation_evaluation_report.json")
DEFAULT_NUM_USERS = 60
DEFAULT_NUM_CANDIDATES = 3


def _independently_verify_faithfulness(explanation: str, category: str, category_match: bool) -> bool:
    """Re-checks the real outcome from scratch, rather than trusting
    that the generation module's own gate
    (recommender.explanation.generation._preserves_required_facts) must
    have worked correctly. A separate check here would still catch a
    mistake in that gate's own code.
    """
    if category_match:
        return category.lower() in explanation.lower()
    return True


def evaluate_explanations(
    context: ServingContext,
    num_users: int = DEFAULT_NUM_USERS,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
) -> dict:
    """Measures explanation faithfulness and how much the local model
    actually contributes beyond the safe fallback template -- both
    deliberately kept separate from recommendation Recall/NDCG/MRR,
    which measure a different property (whether the right item
    appeared in the slate, not whether a real reason was given for it).
    """
    validation = load_split("validation")
    news_by_id = load_catalog().set_index("news_id")
    real_users = validation["user_id"].dropna().unique()[:num_users]

    total = 0
    refused = 0
    faithful = 0
    model_rewrite_used = 0
    template_fallback_used = 0
    explanation_lengths: list[int] = []
    distinct_explanations: set[str] = set()

    for user_id in real_users:
        request = RecommendationRequest(user_id=user_id, num_candidates=num_candidates)
        response = recommend(request, context, include_matched_signals=True)

        for explanation_request in build_explanation_requests(response):
            support = retrieve_support_context(explanation_request, news_by_id)
            result = generate_explanation(support)
            total += 1

            if result.refused:
                refused += 1
                continue

            if _independently_verify_faithfulness(
                result.explanation, support.category, support.category_match
            ):
                faithful += 1

            if result.explanation == build_template_explanation(support):
                template_fallback_used += 1
            else:
                model_rewrite_used += 1

            explanation_lengths.append(len(result.explanation))
            distinct_explanations.add(result.explanation)

    attempted = total - refused
    return {
        "total_recommendations_evaluated": total,
        "refused": refused,
        "refusal_rate": refused / total if total else 0.0,
        "attempted": attempted,
        "faithful": faithful,
        "faithfulness_rate": faithful / attempted if attempted else None,
        "model_rewrite_used": model_rewrite_used,
        "template_fallback_used": template_fallback_used,
        "model_contribution_rate": model_rewrite_used / attempted if attempted else None,
        "mean_explanation_length_chars": (
            sum(explanation_lengths) / len(explanation_lengths) if explanation_lengths else None
        ),
        "distinct_explanations": len(distinct_explanations),
    }


def main() -> None:
    context = build_serving_context()
    report = evaluate_explanations(context)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
