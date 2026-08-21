from datetime import datetime

import pytest
from pydantic import ValidationError

from recommender.serving.contract import (
    MAX_NUM_CANDIDATES,
    RecommendationRequest,
    RecommendationResponse,
    RecommendedItem,
)


def test_request_defaults_num_candidates_to_the_frozen_top_k():
    request = RecommendationRequest(user_id="u1")

    assert request.num_candidates == 10
    assert request.request_time is None


def test_request_rejects_an_empty_user_id():
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id="")


def test_request_rejects_a_non_positive_candidate_count():
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id="u1", num_candidates=0)


def test_request_rejects_a_candidate_count_above_the_maximum():
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id="u1", num_candidates=MAX_NUM_CANDIDATES + 1)


def test_recommended_item_rejects_a_score_outside_zero_to_one():
    with pytest.raises(ValidationError):
        RecommendedItem(news_id="n1", score=1.5, rank=1)


def test_recommended_item_rejects_a_non_positive_rank():
    with pytest.raises(ValidationError):
        RecommendedItem(news_id="n1", score=0.5, rank=0)


def test_response_round_trips_through_json():
    response = RecommendationResponse(
        user_id="u1",
        recommendations=[RecommendedItem(news_id="n1", score=0.42, rank=1, category="sports")],
        durable_features_used=True,
        recent_features_used=False,
        generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001 -- naive, matches MIND's own undocumented-timezone timestamps
    )

    restored = RecommendationResponse.model_validate_json(response.model_dump_json())

    assert restored == response
