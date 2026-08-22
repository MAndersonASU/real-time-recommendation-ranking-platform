from pydantic import BaseModel, Field

from recommender.serving.contract import MatchedSignals, RecommendationResponse, RecommendedItem


class ExplanationRequest(BaseModel):
    """One request to explain a single, already-decided recommendation.
    `recommended_item` and `matched_signals` are both pulled from an
    already-produced `RecommendationResponse` -- this type has no field
    that could hold a candidate pool or a user's raw history, so it is
    structurally unable to carry enough information to re-rank or
    re-select anything, only to describe a decision already made.
    """

    user_id: str = Field(min_length=1)
    recommended_item: RecommendedItem
    matched_signals: MatchedSignals


class ExplanationResponse(BaseModel):
    """`refused` is required, not inferred from an empty `explanation`
    string -- this phase's own requirement is an explicit refusal when
    real evidence is insufficient, not a plausible-sounding guess, and a
    caller should never have to guess which kind of response this is.
    `evidence_used` names exactly which real signals the explanation
    text is grounded in, so a claim can be checked against them.
    """

    news_id: str
    explanation: str
    refused: bool
    evidence_used: list[str]


def build_explanation_requests(response: RecommendationResponse) -> list[ExplanationRequest]:
    """Builds one ExplanationRequest per recommended item, using only
    values already present in an already-finished RecommendationResponse
    (built with `recommend(..., include_matched_signals=True)`). Takes a
    finished response as its only input -- there is no path from this
    function back into retrieval, ranking, or reranking.
    """
    if response.matched_signals is None:
        raise ValueError(
            "response.matched_signals is None -- rebuild it with "
            "recommend(..., include_matched_signals=True) before requesting explanations"
        )
    return [
        ExplanationRequest(
            user_id=response.user_id,
            recommended_item=item,
            matched_signals=response.matched_signals[item.news_id],
        )
        for item in response.recommendations
    ]
