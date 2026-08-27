import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import TOP_K, load_split
from recommender.evaluation.sampling import (
    DEFAULT_SAMPLE_SEED,
    describe_sample,
    sample_impression_ids,
)
from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext

DEFAULT_NUM_IMPRESSIONS = 500


def evaluate_via_replay(
    context: ServingContext,
    num_impressions: int = DEFAULT_NUM_IMPRESSIONS,
    k: int = TOP_K,
    replay: pd.DataFrame | None = None,
    use_recent_features: bool = True,
    sample_seed: int = DEFAULT_SAMPLE_SEED,
) -> dict:
    """Runs the real, full recommend() pipeline -- retrieval, ranking,
    reranking, all of it -- against real historical impressions from the
    reserved `replay` split, checking whether the live system's slate
    would have contained the item the user actually went on to click.

    This is a simulation, explicitly not a real online A/B test: every
    call uses whatever online-feature state happens to exist right now
    (the durable cache built from `validation`, and Redis's current
    contents), not the exact point-in-time state a truly live system
    would have had at each impression's real historical moment. That gap
    is real and disclosed here, not hidden -- docs/limitations.md records
    it as a named limitation, not a surprise sprung there for the first
    time.

    Sampled to `num_impressions`, not the full ~73k-impression split,
    since each one is a real, full pipeline call -- the same accepted
    sampling tradeoff `build_index.py` already made for retrieval's own
    query-embedding benchmark. The sample is a seeded uniform draw of
    impression ids over the whole split, restored to chronological
    `(time, impression_id)` order before replay -- an earlier version
    took `replay.head(num_impressions)`, the first impression rows in
    the split's own on-disk order, which is not a representative sample
    of the day and is not even guaranteed to be the chronologically
    earliest rows.

    `use_recent_features=False` runs the recent-streaming-features
    ablation (docs/experiments/ablations.md): every call forces the online lookup to
    skip Redis entirely, as if no live Kafka/Redis feed existed. Each
    call's real `feature_lookup_ms` is collected via `stage_timings` so
    the ablation's latency change, not just its quality change, comes
    from an actual measurement of this exact run.
    """
    replay = replay if replay is not None else load_split("replay")
    selected_ids = sample_impression_ids(replay, num_impressions, seed=sample_seed)
    sampling = describe_sample(replay, selected_ids, seed=sample_seed)
    sampled = replay[replay["impression_id"].isin(selected_ids)].sort_values(
        ["time", "impression_id"]
    )
    exploded = explode_impressions(sampled)

    hits = 0
    impressions_with_clicks = 0
    feature_lookup_ms_samples = []
    for _impression_id, group in exploded.groupby("impression_id", sort=False):
        clicked_ids = set(group.loc[group["clicked"] == 1, "news_id"])
        if not clicked_ids:
            continue
        impressions_with_clicks += 1

        user_id = group["user_id"].iloc[0]
        # Passes the impression's own real historical timestamp as
        # request_time, so freshness reranking during replay
        # (apply_freshness_quota, which can swap items into the slate
        # based on age) behaves the way it would have at the real
        # historical moment being replayed, rather than falling back to
        # the real wall clock and scoring every 2019 replay impression
        # as thousands of days old regardless of its real age.
        request_time = group["time"].iloc[0]
        request = RecommendationRequest(user_id=user_id, num_candidates=k, request_time=request_time)
        stage_timings: dict[str, float] = {}
        response = safe_recommend(
            request, context, stage_timings=stage_timings, use_recent_features=use_recent_features
        )
        if "feature_lookup_ms" in stage_timings:
            feature_lookup_ms_samples.append(stage_timings["feature_lookup_ms"])
        recommended_ids = {item.news_id for item in response.recommendations}
        hits += int(bool(clicked_ids & recommended_ids))

    return {
        "impressions_sampled": num_impressions,
        "impressions_with_a_real_click": impressions_with_clicks,
        "k": k,
        "hit_rate_at_k": hits / impressions_with_clicks if impressions_with_clicks else 0.0,
        "is_a_replay_simulation_not_a_live_ab_test": True,
        "use_recent_features": use_recent_features,
        "mean_feature_lookup_ms": (
            float(np.mean(feature_lookup_ms_samples)) if feature_lookup_ms_samples else None
        ),
        "sampling": sampling,
    }
