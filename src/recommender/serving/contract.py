from datetime import datetime

from pydantic import BaseModel, Field

from recommender.evaluation.contract import TOP_K

MAX_NUM_CANDIDATES = 50


class RecommendationRequest(BaseModel):
    """One request for a user's recommendation slate. `request_time` is
    optional context, not a required field -- a caller with no notion of
    "now" (a batch replay, a test) should still be able to build a valid
    request, with the server supplying the real clock time itself.
    """

    user_id: str = Field(min_length=1)
    num_candidates: int = Field(default=TOP_K, gt=0, le=MAX_NUM_CANDIDATES)
    request_time: datetime | None = None


class RecommendedItem(BaseModel):
    """One item in a response slate. `rank` is 1-indexed position within
    this response, not a global popularity rank -- explicit so a caller
    doesn't have to infer position from list order alone. `score` is
    bounded to [0, 1] because the ranking model (Phase 4) is a calibrated
    probability, not an unbounded raw score -- a value outside that range
    would mean something upstream is already broken, not a valid edge case
    a caller needs to handle.
    """

    news_id: str
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(gt=0)
    category: str | None = None


class RecommendationResponse(BaseModel):
    """The full response for one request. `durable_features_used` and
    `recent_features_used` surface Phase 7's cold-start fallback signal
    (`OnlineFeatureLookup.durable_is_fallback` / `recent_is_fallback`,
    inverted here since a caller cares whether real personalization
    happened, not whether a fallback fired) directly to the caller,
    rather than letting a degraded, fallback-heavy recommendation look
    identical to a fully personalized one.
    """

    user_id: str
    recommendations: list[RecommendedItem]
    durable_features_used: bool
    recent_features_used: bool
    generated_at: datetime
