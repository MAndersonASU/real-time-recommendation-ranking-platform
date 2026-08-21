from recommender.serving.contract import RecommendationRequest
from recommender.serving.pipeline import recommend
from tests.test_pipeline import _build_context

EXPECTED_STAGES = {
    "feature_lookup_ms", "embedding_ms", "retrieval_ms",
    "feature_build_ms", "ranking_ms", "reranking_ms",
}


def test_stage_timings_are_empty_by_default():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    recommend(request, context)  # no stage_timings passed -- must not raise


def test_stage_timings_records_every_stage_when_requested():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=3)
    stage_timings: dict[str, float] = {}

    recommend(request, context, stage_timings=stage_timings)

    assert set(stage_timings.keys()) == EXPECTED_STAGES
    assert all(value >= 0.0 for value in stage_timings.values())


def test_stage_timings_do_not_change_the_actual_response():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    without_timings = recommend(request, context)
    with_timings = recommend(request, context, stage_timings={})

    assert without_timings.model_dump(exclude={"generated_at"}) == with_timings.model_dump(
        exclude={"generated_at"}
    )
