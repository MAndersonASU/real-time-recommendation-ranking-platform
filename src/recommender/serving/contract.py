from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from recommender.evaluation.contract import TOP_K

MAX_NUM_CANDIDATES = 50


# A conservative bound: comfortably above any real identifier, far
# below anything that would strain a key, a log line or a page.
MAX_USER_ID_LENGTH = 128
# A positive allow-list, not a denial list. Excluding ASCII control
# characters still admitted non-printing Unicode format characters --
# a zero-width space, a bidirectional mark, a byte-order mark -- which
# are invisible in a log line and in a rendered page while producing a
# distinct Redis key. Enumerating what an identifier may contain avoids
# chasing that category indefinitely.
USER_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"


class RecommendationRequest(BaseModel):
    """One request for a user's recommendation slate. `request_time` is
    optional context, not a required field -- a caller with no notion of
    "now" (a batch replay, a test) should still be able to build a valid
    request, with the server supplying the real clock time itself.
    """

    # Bounded on both ends. A minimum alone let an arbitrarily large id
    # through, and that id reaches a Redis key, a hash, a log line and a
    # rendered page -- so an unbounded value is a cheap way to inflate
    # memory and log volume. 128 characters is far above any real MIND
    # id (typically under 10) while staying safely bounded.
    #
    # The pattern additionally excludes whitespace and control
    # characters, which would otherwise corrupt log lines and key names
    # without ever being a legitimate identifier.
    user_id: str = Field(min_length=1, max_length=MAX_USER_ID_LENGTH, pattern=USER_ID_PATTERN)
    num_candidates: int = Field(default=TOP_K, gt=0, le=MAX_NUM_CANDIDATES)
    request_time: datetime | None = None

    @field_validator("request_time")
    @classmethod
    def _normalize_to_naive_utc(cls, value: datetime | None) -> datetime | None:
        """A real, reproducible bug: a tz-aware `request_time` (any
        ISO 8601 string with a `Z` or `+00:00` offset -- ordinary,
        correct client input) passed this field's original bare
        `datetime | None` type with no error, then crashed recommendation
        generation downstream with `TypeError: Cannot subtract tz-naive
        and tz-aware datetime-like objects` when compared against the
        naive `first_seen` timestamps every other part of this project
        uses (docs/dataset-source.md: MIND's own timestamps carry no
        timezone). Normalizing here, at the one boundary where untrusted
        input enters the system, means every downstream consumer keeps
        working with the naive datetimes it already assumes -- instead
        of every caller of `request_time` needing to guess how to handle
        a tz-aware value.
        """
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value


class RecommendedItem(BaseModel):
    """One item in a response slate. `rank` is 1-indexed position within
    this response, not a global popularity rank -- explicit so a caller
    doesn't have to infer position from list order alone. `score` is
    bounded to [0, 1] because the ranking model is a calibrated
    probability, not an unbounded raw score -- a value outside that range
    would mean something upstream is already broken, not a valid edge case
    a caller needs to handle.
    """

    news_id: str
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(gt=0)
    category: str | None = None


class MatchedSignals(BaseModel):
    """The real ranking-model input features that produced one item's
    score, captured directly from the same feature row `recommend()`
    already builds -- never recomputed or re-derived. The only
    legitimate source of "why" the explanation layer
    (recommender.explanation) can draw from.
    """

    category_match: bool
    content_similarity: float
    retrieval_score: float
    user_history_length: int = Field(ge=0)


class RecommendationResponse(BaseModel):
    """The full response for one request. `durable_features_used` and
    `recent_features_used` surface the online feature store's cold-start fallback signal
    (`OnlineFeatureLookup.durable_is_fallback` / `recent_is_fallback`,
    inverted here since a caller cares whether real personalization
    happened, not whether a fallback fired) directly to the caller,
    rather than letting a degraded, fallback-heavy recommendation look
    identical to a fully personalized one.

    `matched_signals`, keyed by `news_id`, is only populated when the
    caller opts in (`recommend(..., include_matched_signals=True)`) --
    left `None` by default so an ordinary request pays no extra cost for
    data only the optional explanation layer ever needs.
    """

    user_id: str
    recommendations: list[RecommendedItem]
    durable_features_used: bool
    recent_features_used: bool
    generated_at: datetime
    matched_signals: dict[str, MatchedSignals] | None = None
