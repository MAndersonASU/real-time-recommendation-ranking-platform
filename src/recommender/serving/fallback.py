from collections.abc import Callable
from datetime import datetime

import numpy as np
import pandas as pd
import redis

from recommender.ranking.baselines import rank_by_popularity
from recommender.serving.contract import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendedItem,
)
from recommender.serving.pipeline import ServingContext, recommend

# Deliberately narrow and specific, not a bare `except Exception` -- the
# same discipline the streaming consumer already applies to malformed
# messages (docs/streaming-consumer.md): catching everything would risk
# silently hiding a real logic bug behind a "safe" fallback. RedisError
# covers the feature store being unreachable; RuntimeError is the common
# base both torch and Faiss raise for an unusable model/index; OSError
# covers a missing or unreadable model file on disk.
DEPENDENCY_FAILURE_EXCEPTIONS = (redis.exceptions.RedisError, RuntimeError, OSError)


def _normalized_popularity(popularity: pd.Series, news_ids) -> np.ndarray:
    values = np.array([popularity.get(nid, 0) for nid in news_ids], dtype=float)
    max_value = values.max() if len(values) else 0.0
    return values / max_value if max_value > 0 else np.zeros(len(values))


def build_fallback_response(request: RecommendationRequest, context: ServingContext) -> RecommendationResponse:
    """A response built without needing the two-tower model, the Faiss
    index, the ranking model, or Redis -- ranks the whole catalog by
    plain training-set popularity, exactly Phase 2's first and simplest
    baseline. `score` here is popularity normalized into [0, 1], not a
    calibrated click probability the way it is on the real path -- an
    honest difference given the contract's [0, 1] bound describes a
    range, not a guarantee of what produced the number. Both feature
    flags are always False: no online feature lookup happens on this
    path at all, so claiming personalization would be dishonest.
    """
    catalog = pd.DataFrame({"news_id": context.news_ids})
    ranked = rank_by_popularity(catalog, context.popularity)
    top = ranked.head(request.num_candidates).reset_index(drop=True)
    scores = _normalized_popularity(context.popularity, top["news_id"])

    recommendations = [
        RecommendedItem(
            news_id=row.news_id,
            score=float(scores[i]),
            rank=i + 1,
            category=context.category_by_id.get(row.news_id),
        )
        for i, row in enumerate(top.itertuples())
    ]

    return RecommendationResponse(
        user_id=request.user_id,
        recommendations=recommendations,
        durable_features_used=False,
        recent_features_used=False,
        generated_at=datetime.now(),  # noqa: DTZ005 -- naive, matches every other timestamp in this project
    )


def safe_recommend(
    request: RecommendationRequest,
    context: ServingContext,
    on_fallback: Callable[[], None] | None = None,
    stage_timings: dict[str, float] | None = None,
    use_recent_features: bool = True,
    include_matched_signals: bool = False,
) -> RecommendationResponse:
    """The real path, with a safe popularity fallback if a real
    dependency it needs turns out to be unavailable. Deliberately
    separate from Phase 7's cold-start handling inside `recommend`
    itself: cold start answers "we don't know anything about this
    user," which the real path already handles without falling back at
    all; this answers "the real path itself cannot run right now."

    `on_fallback`, when given a callable, is invoked right before a
    fallback response is returned -- opt-in instrumentation of this
    exact branch, rather than a caller inferring "was this a fallback"
    from the response's feature flags, which a genuine cold-start
    response can also legitimately have both set to False.
    `stage_timings`, `use_recent_features`, and `include_matched_signals`
    pass straight through to `recommend()` on the real path (there is no
    per-stage breakdown, recent-features toggle, or matched-signals
    detail for a fallback response, since it never runs those stages at
    all -- `build_fallback_response` always leaves `matched_signals`
    unset).
    """
    try:
        return recommend(
            request,
            context,
            stage_timings=stage_timings,
            use_recent_features=use_recent_features,
            include_matched_signals=include_matched_signals,
        )
    except DEPENDENCY_FAILURE_EXCEPTIONS:
        if on_fallback is not None:
            on_fallback()
        return build_fallback_response(request, context)
