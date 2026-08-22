from datetime import datetime

import pytest

from recommender.explanation.contract import build_explanation_requests
from recommender.serving.contract import MatchedSignals, RecommendationResponse, RecommendedItem

ITEM_A = RecommendedItem(news_id="n1", score=0.8, rank=1, category="sports")
ITEM_B = RecommendedItem(news_id="n2", score=0.5, rank=2, category="tech")

SIGNALS_A = MatchedSignals(
    category_match=True, content_similarity=0.6, retrieval_score=0.3, user_history_length=5
)
SIGNALS_B = MatchedSignals(
    category_match=False, content_similarity=0.0, retrieval_score=0.1, user_history_length=5
)


def _response(matched_signals=None) -> RecommendationResponse:
    return RecommendationResponse(
        user_id="u1",
        recommendations=[ITEM_A, ITEM_B],
        durable_features_used=True,
        recent_features_used=True,
        generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001 -- naive, matches every other timestamp in this project
        matched_signals=matched_signals,
    )


def test_build_explanation_requests_raises_without_matched_signals():
    response = _response(matched_signals=None)

    with pytest.raises(ValueError, match="matched_signals"):
        build_explanation_requests(response)


def test_build_explanation_requests_pairs_each_item_with_its_own_signals():
    response = _response(matched_signals={"n1": SIGNALS_A, "n2": SIGNALS_B})

    requests = build_explanation_requests(response)

    assert len(requests) == 2
    assert requests[0].recommended_item.news_id == "n1"
    assert requests[0].matched_signals == SIGNALS_A
    assert requests[1].recommended_item.news_id == "n2"
    assert requests[1].matched_signals == SIGNALS_B


def test_build_explanation_requests_carries_the_user_id_through():
    response = _response(matched_signals={"n1": SIGNALS_A, "n2": SIGNALS_B})

    requests = build_explanation_requests(response)

    assert all(request.user_id == "u1" for request in requests)
