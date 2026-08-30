from datetime import datetime

import pandas as pd
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


def test_request_time_normalizes_a_z_suffixed_timestamp_to_naive_utc():
    """Regression test for a real bug: a tz-aware request_time (any
    ISO 8601 string with a Z or +00:00 offset -- ordinary client input)
    used to pass this field with no normalization at all, then crash
    recommendation generation downstream with a tz-naive/aware
    subtraction TypeError. Fails on the pre-fix contract (request_time
    keeps tzinfo=utc) and passes once the validator strips it.
    """
    request = RecommendationRequest(user_id="u1", request_time="2019-11-15T08:00:00Z")

    assert request.request_time == datetime(2019, 11, 15, 8, 0, 0)  # noqa: DTZ001 -- asserting naive
    assert request.request_time.tzinfo is None


def test_request_time_converts_a_non_utc_offset_to_naive_utc():
    request = RecommendationRequest(user_id="u1", request_time="2019-11-15T10:00:00+02:00")

    assert request.request_time == datetime(2019, 11, 15, 8, 0, 0)  # noqa: DTZ001 -- 10:00+02:00 == 08:00 UTC
    assert request.request_time.tzinfo is None


def test_request_time_leaves_an_already_naive_datetime_unchanged():
    naive = datetime(2019, 11, 15, 8, 0, 0)  # noqa: DTZ001 -- deliberately naive input
    request = RecommendationRequest(user_id="u1", request_time=naive)

    assert request.request_time == naive
    assert request.request_time.tzinfo is None


def test_request_time_accepts_a_pandas_timestamp_like_replay_evaluation_passes():
    request = RecommendationRequest(user_id="u1", request_time=pd.Timestamp("2019-11-15 08:00:00"))

    assert request.request_time == datetime(2019, 11, 15, 8, 0, 0)  # noqa: DTZ001 -- naive, matches source


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
        retrieval_history_source="durable",
        generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001 -- naive, matches MIND's own undocumented-timezone timestamps
    )

    restored = RecommendationResponse.model_validate_json(response.model_dump_json())

    assert restored == response


def test_retrieval_history_source_rejects_an_unrecognised_value():
    """SERVING-DURABLE-HISTORY-69: this field names which of exactly
    three real code paths drove retrieval -- an arbitrary string here
    would be silently accepted as if it named a fourth, nonexistent one.
    """
    with pytest.raises(ValidationError):
        RecommendationResponse(
            user_id="u1",
            recommendations=[],
            durable_features_used=False,
            recent_features_used=False,
            retrieval_history_source="both",  # not a real retrieval path
            generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001
        )
