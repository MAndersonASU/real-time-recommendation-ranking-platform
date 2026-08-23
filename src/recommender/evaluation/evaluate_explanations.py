import json
import re
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


_COMMON_SENTENCE_STARTERS = {
    "the", "this", "it", "a", "an", "that", "these", "recommended", "its", "you", "your",
}


def _introduces_an_unfounded_capitalized_word(explanation: str, template: str) -> bool:
    """A separate implementation of the same idea the generation
    module's own gate uses, deliberately not imported from there -- the
    whole point of this function is to catch a mistake in that other
    module's code, which importing its helper directly could not do.
    True if `explanation` contains a capitalized word that isn't just a
    re-casing of a real template word and isn't an ordinary sentence
    opener -- what a real invented proper noun looks like. Compared
    case-insensitively against every word in the template (not only its
    own capitalized words) and checked regardless of position, so a
    proper noun that happens to start the sentence ("NASA...") is still
    caught rather than excluded just for being first.
    """
    template_words = {w.lower() for w in re.findall(r"\b[A-Za-z]+\b", template)}
    for word in re.findall(r"\b[A-Za-z]+\b", explanation):
        if not word[0].isupper():
            continue
        lowered = word.lower()
        if lowered in _COMMON_SENTENCE_STARTERS or lowered in template_words:
            continue
        return True
    return False


def _independently_verify_faithfulness(
    explanation: str, category: str, category_match: bool, template: str
) -> bool:
    """Re-checks the real outcome from scratch, rather than trusting
    that the generation module's own gate
    (recommender.explanation.generation._preserves_required_facts) must
    have worked correctly. A separate check here would still catch a
    mistake in that gate's own code -- and did: an earlier version of
    this exact function only checked the category-match branch, so a
    fabricated claim on a content-similarity-only recommendation
    ("The President personally selected this story for you") would
    have been counted as faithful by this "independent" check too,
    since it shared the same blind spot as the code it was meant to
    verify. Both are fixed together now.
    """
    if category_match and category.lower() not in explanation.lower():
        return False
    return not _introduces_an_unfounded_capitalized_word(explanation, template)


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

            template = build_template_explanation(support)
            if _independently_verify_faithfulness(
                result.explanation, support.category, support.category_match, template
            ):
                faithful += 1

            if result.explanation == template:
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
