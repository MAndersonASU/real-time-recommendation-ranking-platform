import pandas as pd
import pytest

from recommender.explanation.contract import ExplanationRequest
from recommender.explanation.retrieval import MAX_ABSTRACT_CHARS, retrieve_support_context
from recommender.serving.contract import MatchedSignals, RecommendedItem

NEWS = pd.DataFrame(
    {
        "news_id": ["n1", "n2"],
        "category": ["sports", "tech"],
        "subcategory": ["football", "gadgets"],
        "title": ["team wins big game", "new phone released"],
        "abstract": ["x" * 500, None],
    }
).set_index("news_id")

SIGNALS = MatchedSignals(
    category_match=True, content_similarity=0.6, retrieval_score=0.3, user_history_length=5
)


def _request(news_id: str) -> ExplanationRequest:
    return ExplanationRequest(
        user_id="u1",
        recommended_item=RecommendedItem(news_id=news_id, score=0.8, rank=1, category="sports"),
        matched_signals=SIGNALS,
    )


def test_retrieve_support_context_pulls_real_catalog_fields():
    context = retrieve_support_context(_request("n1"), NEWS)

    assert context.title == "team wins big game"
    assert context.category == "sports"
    assert context.subcategory == "football"


def test_retrieve_support_context_truncates_a_long_abstract():
    context = retrieve_support_context(_request("n1"), NEWS)

    assert len(context.abstract) == MAX_ABSTRACT_CHARS


def test_retrieve_support_context_handles_a_missing_abstract_as_empty_not_none():
    context = retrieve_support_context(_request("n2"), NEWS)

    assert context.abstract == ""


def test_retrieve_support_context_carries_the_real_matched_signals_through():
    context = retrieve_support_context(_request("n1"), NEWS)

    assert context.category_match is True
    assert context.content_similarity == 0.6
    assert context.retrieval_score == 0.3
    assert context.user_history_length == 5


def test_retrieve_support_context_raises_for_an_unknown_item():
    with pytest.raises(ValueError, match="not found"):
        retrieve_support_context(_request("does-not-exist"), NEWS)
