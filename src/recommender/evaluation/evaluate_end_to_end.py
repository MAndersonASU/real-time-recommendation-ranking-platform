import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import TOP_K, load_catalog, load_split
from recommender.evaluation.metrics import catalog_coverage, hit_rate_at_k, reciprocal_rank
from recommender.evaluation.retrieval_metrics import ndcg_at_n_known_total, recall_at_n_known_total
from recommender.features.fake_redis import InMemoryRedis
from recommender.features.online_features import (
    DurableUserFeatures,
    recent_features_from_user_state,
    user_state_from_recent_features,
)
from recommender.features.state_store import load_recent_features, save_recent_features
from recommender.ranking.features import dominant_category, history_ids_from_raw
from recommender.retrieval.features import MAX_HISTORY
from recommender.serving.cache import DurableFeatureCache
from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext
from recommender.streaming.consumer import UserState

REPORT_PATH = Path("data/processed/mind_small/end_to_end_evaluation_report.json")
DEFAULT_NUM_IMPRESSIONS = 500


def _point_in_time_durable_features(
    user_id: str, history_raw: str | None, category_by_id: pd.Series
) -> DurableUserFeatures:
    """Built from this one impression's own `history` field, not "the
    user's latest row in the split." MIND already records, per
    impression, the user's click history strictly before that
    impression -- reusing any *other* row for the same user (even a
    "most recent in the split" row) would let a later impression's
    information leak into an earlier one's evaluation.
    """
    history_ids = history_ids_from_raw(history_raw) if history_raw else []
    return DurableUserFeatures(
        user_id=user_id,
        dominant_category=dominant_category(history_ids, category_by_id),
        lifetime_click_count=len(history_ids),
    )


def _seed_recent_state_from_history(
    redis_client: InMemoryRedis, user_id: str, history_raw: str | None
) -> None:
    """Seeds a user's isolated recent-feature state, once, from that
    impression's own `history` field -- the clicks MIND records as
    happening strictly *before* this impression, which is exactly what a
    live Redis would already hold for a returning user at that moment.

    Without this, the store starts empty for every user, and the serving
    path's two-tower query is built from an empty click list. That
    produces a genuinely zero-norm user embedding, and an inner-product
    Faiss search against a zero vector scores every catalog item
    identically -- so every user receives the same arbitrary tie-ordered
    candidate list. Measured directly before this fix: 60 impressions
    produced 1 distinct candidate set with the empty store, versus 50
    once real history was supplied.

    Seeded only on a user's first impression in the run; later
    impressions accumulate on top via `_apply_impression_to_recent_state`,
    so a user's second impression correctly sees their prior history
    *plus* the first impression's real clicks.
    """
    if load_recent_features(redis_client, user_id) is not None:
        return
    history_ids = history_ids_from_raw(history_raw) if history_raw else []
    if not history_ids:
        return
    state = UserState()
    for news_id in history_ids[-MAX_HISTORY:]:
        state.recent_clicked_items.append(news_id)
    state.clicks_seen = len(history_ids)
    save_recent_features(redis_client, recent_features_from_user_state(user_id, state))


def _apply_impression_to_recent_state(
    redis_client: InMemoryRedis, user_id: str, clicked_ids: set, request_time
) -> None:
    """Updates the isolated recent-feature state for one user from one
    impression's real events -- called only after that impression has
    already been scored, so its own events can never influence its own
    recommendation, only a later one. Reuses the same real state
    conversion helpers (`user_state_from_recent_features`,
    `recent_features_from_user_state`) and the same bounded-deque
    `UserState` the live streaming consumer uses, so a click here is
    tracked identically to a real streaming event.
    """
    existing = load_recent_features(redis_client, user_id)
    state = user_state_from_recent_features(existing) if existing is not None else UserState()
    state.impressions_seen += 1
    for news_id in clicked_ids:
        state.clicks_seen += 1
        state.recent_clicked_items.append(news_id)
    state.last_event_time = str(request_time)
    save_recent_features(redis_client, recent_features_from_user_state(user_id, state))


def evaluate_end_to_end(
    context: ServingContext,
    num_impressions: int = DEFAULT_NUM_IMPRESSIONS,
    k: int = TOP_K,
    validation: pd.DataFrame | None = None,
    news: pd.DataFrame | None = None,
) -> dict:
    """Runs the real serving code path (`safe_recommend`, retrieval ->
    ranking -> reranking, exactly what `/recommend` calls) against real
    validation-split impressions, processed in real chronological order
    with point-in-time-correct state: each impression's durable features
    come only from that impression's own `history` field, and its recent
    features come only from an isolated, in-run state store containing
    strictly earlier impressions' real events -- never `context`'s own
    shared `durable_cache` or `redis_client`, and never a later
    impression's information. State is applied to the isolated store
    only *after* an impression has been scored, so a later event can
    never change an earlier recommendation (`tests/
    test_evaluate_end_to_end.py` proves this directly, not just by
    construction).

    This is a serving-path evaluation, not a claim about what a live
    deployment's actual traffic and timing would produce: real request
    concurrency, real Kafka/Redis latency, and real durable-feature
    refresh cadence are not reproduced here. `docs/ranking-features.md`
    already discloses a separate, deliberate choice: the frozen ranking
    protocol scores MIND's own impression candidate list, not real
    Faiss-retrieved candidates. This function's own real candidates
    (retrieval's actual top-N) are reported alongside that protocol's
    numbers, not in place of them.
    """
    validation = validation if validation is not None else load_split("validation")
    validation = validation.sort_values("time").head(num_impressions).reset_index(drop=True)
    exploded = explode_impressions(validation)
    history_by_impression_id = validation.set_index("impression_id")["history"]
    news = news if news is not None else load_catalog()
    category_by_id = news.set_index("news_id")["category"]

    isolated_redis = InMemoryRedis()

    hit_rates: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []
    reciprocal_ranks: list[float] = []
    impressions_evaluated = 0
    skip_reasons: Counter = Counter()
    fallback_reasons: Counter = Counter()
    durable_hits = 0
    recent_hits = 0
    retrieval_contained_a_click = 0
    all_recommended_ids: set = set()

    for impression_id, group in exploded.groupby("impression_id", sort=False):
        clicked_ids = set(group.loc[group["clicked"] == 1, "news_id"])
        if not clicked_ids:
            skip_reasons["no_real_click"] += 1
            continue
        true_relevant_count = len(clicked_ids)

        user_id = group["user_id"].iloc[0]
        request_time = group["time"].iloc[0]

        history_raw = history_by_impression_id.get(impression_id)
        durable = _point_in_time_durable_features(user_id, history_raw, category_by_id)
        _seed_recent_state_from_history(isolated_redis, user_id, history_raw)
        per_impression_context = replace(
            context,
            durable_cache=DurableFeatureCache(features_by_user={user_id: durable}, computed_at=request_time),
            redis_client=isolated_redis,
        )

        request = RecommendationRequest(user_id=user_id, num_candidates=k, request_time=request_time)

        fallback_state = {"value": False, "reason": None}

        def _mark_fallback(reason: str, state=fallback_state) -> None:
            state["value"] = True
            state["reason"] = reason

        retrieved_ids: list = []
        response = safe_recommend(
            request, per_impression_context, on_fallback=_mark_fallback,
            capture_candidates=retrieved_ids,
        )
        impressions_evaluated += 1
        if clicked_ids & set(retrieved_ids):
            retrieval_contained_a_click += 1
        if fallback_state["value"]:
            fallback_reasons[fallback_state["reason"]] += 1
        if response.durable_features_used:
            durable_hits += 1
        if response.recent_features_used:
            recent_hits += 1

        recommended_ids = [item.news_id for item in response.recommendations]
        all_recommended_ids.update(recommended_ids)
        relevance = np.array([1 if nid in clicked_ids else 0 for nid in recommended_ids])

        hit_rates.append(hit_rate_at_k(relevance, k))
        recalls.append(recall_at_n_known_total(relevance, true_relevant_count, k))
        ndcgs.append(ndcg_at_n_known_total(relevance, true_relevant_count, k))
        reciprocal_ranks.append(reciprocal_rank(relevance))

        # Applied only now, after this impression has already been
        # scored -- so it can only affect a strictly later impression's
        # recent-feature state, never its own or an earlier one's.
        _apply_impression_to_recent_state(isolated_redis, user_id, clicked_ids, request_time)

    total_impressions = impressions_evaluated + sum(skip_reasons.values())
    return {
        "k": k,
        "impressions_in_sample": total_impressions,
        "impressions_evaluated": impressions_evaluated,
        "impressions_skipped": dict(skip_reasons),
        "durable_feature_coverage": durable_hits / impressions_evaluated if impressions_evaluated else None,
        "recent_feature_coverage": recent_hits / impressions_evaluated if impressions_evaluated else None,
        "fallback_count": sum(fallback_reasons.values()),
        "fallback_reasons": dict(fallback_reasons),
        "catalog_coverage": catalog_coverage(all_recommended_ids, len(context.news_ids)),
        # Separates a retrieval miss from a ranking miss. If this is near
        # zero, the clicked item was never a candidate at all, and no
        # amount of ranking improvement could raise the metrics below --
        # the end-to-end numbers alone cannot tell those two failures
        # apart, which is why this is reported alongside them.
        "retrieval_contained_a_click_rate": (
            retrieval_contained_a_click / impressions_evaluated if impressions_evaluated else None
        ),
        "hit_rate_at_k": float(np.mean(hit_rates)) if hit_rates else 0.0,
        "recall_at_k": float(np.mean(recalls)) if recalls else 0.0,
        "ndcg_at_k": float(np.mean(ndcgs)) if ndcgs else 0.0,
        "mrr": float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0,
    }


def main() -> None:
    from recommender.serving.pipeline import build_serving_context

    context = build_serving_context()
    report = evaluate_end_to_end(context)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
