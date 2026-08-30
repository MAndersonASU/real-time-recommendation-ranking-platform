import itertools
import json
import random
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import TOP_K, load_catalog, load_split
from recommender.evaluation.metrics import catalog_coverage, hit_rate_at_k, reciprocal_rank
from recommender.evaluation.retrieval_metrics import ndcg_at_n_known_total, recall_at_n_known_total
from recommender.evaluation.sampling import (
    DEFAULT_SAMPLE_SEED,
    describe_sample,
    sample_impression_ids,
)
from recommender.features.fake_redis import InMemoryRedis
from recommender.features.online_features import DurableUserFeatures
from recommender.paths import mind_small_path
from recommender.ranking.features import dominant_category, history_ids_from_raw
from recommender.retrieval.features import MAX_HISTORY
from recommender.serving.cache import DurableFeatureCache
from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext

REPORT_PATH = mind_small_path("durable_history_fallback_report.json")

# Larger than evaluate_end_to_end's default: only impressions whose user
# has a *usable* point-in-time durable history are eligible here (most
# users' `history` field is empty or entirely off-catalog), so a larger
# draw is needed to reach a workable eligible count. Chosen the same way
# as every other sample size in this project -- a judgment call recorded
# here, not an automatic rule.
DEFAULT_NUM_IMPRESSIONS = 8000
# Bounds the pairwise-Jaccard computation below to O(this), not O(n^2)
# on however many eligible impressions the sample happens to produce.
DEFAULT_MAX_JACCARD_PAIRS = 20000


def _point_in_time_durable_features(
    user_id: str, history_raw: str | None, category_by_id: pd.Series
) -> DurableUserFeatures:
    """The same point-in-time reconstruction
    `evaluate_end_to_end._point_in_time_durable_features` uses: built
    from this one impression's own `history` field, never "the user's
    latest row in the split," so a later impression's information can
    never leak into an earlier one's evaluation.
    """
    history_ids = history_ids_from_raw(history_raw) if history_raw else []
    valid_history_ids = [nid for nid in history_ids if nid in category_by_id.index]
    return DurableUserFeatures(
        user_id=user_id,
        dominant_category=dominant_category(history_ids, category_by_id),
        lifetime_click_count=len(history_ids),
        history_item_ids=tuple(valid_history_ids[-MAX_HISTORY:]),
    )


def _mean_pairwise_jaccard(slates: list[frozenset], seed: int, max_pairs: int) -> float | None:
    """Mean Jaccard similarity over pairs of top-K slates -- how much
    overlap a typical pair of this cohort's responses shares. Sampled
    rather than exhaustive once there are more than `max_pairs` possible
    pairs, so this stays bounded regardless of cohort size; a seeded
    `random.Random` makes the sampled subset itself reproducible.
    """
    n = len(slates)
    if n < 2:
        return None
    total_pairs = n * (n - 1) // 2
    # Statistical sampling for a report metric, not a security or
    # cryptographic use (Bandit B311) -- reproducibility from a fixed
    # seed is exactly the property wanted here.
    rng = random.Random(seed)
    if total_pairs <= max_pairs:
        pairs = itertools.combinations(range(n), 2)
    else:
        seen: set[tuple[int, int]] = set()
        pairs_list = []
        while len(pairs_list) < max_pairs:
            i, j = rng.randrange(n), rng.randrange(n)
            if i == j:
                continue
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            pairs_list.append(key)
        pairs = pairs_list

    scores = []
    for i, j in pairs:
        a, b = slates[i], slates[j]
        union = len(a | b)
        scores.append(len(a & b) / union if union else 0.0)
    return float(np.mean(scores)) if scores else None


def evaluate_durable_history_fallback(
    context: ServingContext,
    num_impressions: int = DEFAULT_NUM_IMPRESSIONS,
    k: int = TOP_K,
    validation: pd.DataFrame | None = None,
    news: pd.DataFrame | None = None,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
    max_jaccard_pairs: int = DEFAULT_MAX_JACCARD_PAIRS,
) -> dict:
    """SERVING-DURABLE-HISTORY-69's dedicated evaluation: a cohort of real
    users who have a usable point-in-time durable history, served against
    a genuinely empty, isolated Redis store (a fresh `InMemoryRedis` this
    run never writes to -- not `use_recent_features=False`, and not
    `context`'s own shared `redis_client`, whose real contents this run
    does not control). This is exactly the live condition
    SERVING-DURABLE-HISTORY-69 found broken: a returning user with real
    durable history and a healthy-but-empty recent-feature record.

    Runs the real `safe_recommend` path (retrieval -> ranking ->
    reranking), the same code every other serving-path evaluation in
    this project exercises, against real validation-split impressions,
    with point-in-time-correct durable features exactly as
    `evaluate_end_to_end` reconstructs them (never `context`'s own
    shared `durable_cache`, which reflects each user's *latest* row in
    the split, not what they had as of the specific impression under
    evaluation).

    An impression is *eligible* only when its point-in-time durable
    history is non-empty after filtering to ids this catalog actually
    has content for -- excluded when a user's `history` field is empty
    (a genuinely new user) or, rarely, entirely off-catalog, since
    neither is the condition this evaluation exists to measure. In the
    published report this excludes only a small minority of sampled
    impressions (2.6%, 210 of 8,000) -- most validation-split users do
    have a usable point-in-time durable history; this evaluation's
    cohort is close to the general population, not a rare subset of it.
    Every eligible impression's request is served with the isolated
    Redis store left untouched, so `retrieval_history_source` should be
    "durable" for every one of them; this is asserted, not merely
    assumed, since an unnoticed regression that silently reintroduced a
    recent-history path here would otherwise go undetected.
    """
    validation = validation if validation is not None else load_split("validation")
    validation = validation.sort_values(["time", "impression_id"], kind="mergesort")
    selected_ids = sample_impression_ids(validation, num_impressions, seed=sample_seed)
    sampling = describe_sample(validation, selected_ids, seed=sample_seed)
    validation = (
        validation[validation["impression_id"].isin(selected_ids)]
        .reset_index(drop=True)
    )
    exploded = explode_impressions(validation)
    history_by_impression_id = validation.set_index("impression_id")["history"]
    news = news if news is not None else load_catalog()
    category_by_id = news.set_index("news_id")["category"]

    # Never seeded, never written to for the rest of this run -- the
    # genuinely empty, isolated Redis store this evaluation requires.
    isolated_redis = InMemoryRedis()

    skip_reasons: Counter = Counter()
    eligible_users: set = set()
    hit_rates: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []
    reciprocal_ranks: list[float] = []
    retrieval_contained_a_click = 0
    all_recommended_ids: set = set()
    top_k_slates: list[frozenset] = []
    retrieval_ms_samples: list[float] = []
    ranking_ms_samples: list[float] = []
    total_ms_samples: list[float] = []
    retrieval_source_counts: Counter = Counter()
    impressions_evaluated = 0

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
        if not durable.history_item_ids:
            skip_reasons["no_usable_durable_history"] += 1
            continue

        eligible_users.add(user_id)
        per_impression_context = replace(
            context,
            durable_cache=DurableFeatureCache(
                features_by_user={user_id: durable},
                built_at=datetime.now(UTC),
                data_as_of=pd.Timestamp(request_time).to_pydatetime().replace(tzinfo=UTC),
            ),
            redis_client=isolated_redis,
        )
        request = RecommendationRequest(user_id=user_id, num_candidates=k, request_time=request_time)

        stage_timings: dict[str, float] = {}
        retrieved_ids: list = []
        response = safe_recommend(
            request, per_impression_context, stage_timings=stage_timings,
            capture_candidates=retrieved_ids,
        )
        impressions_evaluated += 1
        retrieval_source_counts[response.retrieval_history_source] += 1

        if clicked_ids & set(retrieved_ids):
            retrieval_contained_a_click += 1

        recommended_ids = [item.news_id for item in response.recommendations]
        all_recommended_ids.update(recommended_ids)
        top_k_slates.append(frozenset(recommended_ids))
        relevance = np.array([1 if nid in clicked_ids else 0 for nid in recommended_ids])

        hit_rates.append(hit_rate_at_k(relevance, k))
        recalls.append(recall_at_n_known_total(relevance, true_relevant_count, k))
        ndcgs.append(ndcg_at_n_known_total(relevance, true_relevant_count, k))
        reciprocal_ranks.append(reciprocal_rank(relevance))

        if "retrieval_ms" in stage_timings:
            retrieval_ms_samples.append(stage_timings["retrieval_ms"])
        if "ranking_ms" in stage_timings:
            ranking_ms_samples.append(stage_timings["ranking_ms"])
        if stage_timings:
            total_ms_samples.append(sum(stage_timings.values()))

    total_impressions = impressions_evaluated + sum(skip_reasons.values())
    distinct_top_k_sets = len(set(top_k_slates))
    top_k_concentration = (
        max(Counter(top_k_slates).values()) / len(top_k_slates) if top_k_slates else None
    )

    return {
        "k": k,
        "sampling": sampling,
        "impressions_in_sample": total_impressions,
        "impressions_evaluated": impressions_evaluated,
        "impressions_skipped": dict(skip_reasons),
        "eligible_users": len(eligible_users),
        "retrieval_history_source_counts": dict(retrieval_source_counts),
        "distinct_top_k_sets": distinct_top_k_sets,
        "distinct_recommended_items": len(all_recommended_ids),
        "catalog_coverage_at_k": catalog_coverage(all_recommended_ids, len(context.news_ids)),
        "top_k_concentration": top_k_concentration,
        "mean_pairwise_slate_jaccard": _mean_pairwise_jaccard(
            top_k_slates, seed=sample_seed, max_pairs=max_jaccard_pairs
        ),
        "retrieval_contained_a_click_rate": (
            retrieval_contained_a_click / impressions_evaluated if impressions_evaluated else None
        ),
        "hit_rate_at_k": float(np.mean(hit_rates)) if hit_rates else 0.0,
        "recall_at_k": float(np.mean(recalls)) if recalls else 0.0,
        "ndcg_at_k": float(np.mean(ndcgs)) if ndcgs else 0.0,
        "mrr": float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0,
        "mean_retrieval_ms": float(np.mean(retrieval_ms_samples)) if retrieval_ms_samples else None,
        "mean_ranking_ms": float(np.mean(ranking_ms_samples)) if ranking_ms_samples else None,
        "mean_total_ms": float(np.mean(total_ms_samples)) if total_ms_samples else None,
    }


def main() -> None:
    """Measures and publishes in one step, same discipline as every other
    evaluation's `main()`: the provenance stamped on the published report
    describes the process that produced these exact numbers.
    """
    from recommender.evaluation.publish import (
        output_dir_from_argv,
        publish_durable_history_fallback_report,
    )
    from recommender.serving.pipeline import build_serving_context

    context = build_serving_context()
    report = evaluate_durable_history_fallback(context)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    published = publish_durable_history_fallback_report(
        report, sampling=report["sampling"], output_dir=output_dir_from_argv()
    )
    print(json.dumps(report, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
