import numpy as np
import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import TOP_K, load_split
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
    is real and disclosed here, not hidden -- Step 9.4 records it as a
    named limitation, not a surprise sprung there for the first time.

    Sampled to `num_impressions`, not the full ~73k-impression split,
    since each one is a real, full pipeline call -- the same accepted
    sampling tradeoff `build_index.py` already made for retrieval's own
    query-embedding benchmark.

    `use_recent_features=False` runs the recent-streaming-features
    ablation (docs/ablations.md): every call forces the online lookup to
    skip Redis entirely, as if no live Kafka/Redis feed existed. Each
    call's real `feature_lookup_ms` is collected via `stage_timings` so
    the ablation's latency change, not just its quality change, comes
    from an actual measurement of this exact run.
    """
    replay = replay if replay is not None else load_split("replay")
    exploded = explode_impressions(replay.head(num_impressions))

    hits = 0
    impressions_with_clicks = 0
    feature_lookup_ms_samples = []
    for _impression_id, group in exploded.groupby("impression_id", sort=False):
        clicked_ids = set(group.loc[group["clicked"] == 1, "news_id"])
        if not clicked_ids:
            continue
        impressions_with_clicks += 1

        user_id = group["user_id"].iloc[0]
        request = RecommendationRequest(user_id=user_id, num_candidates=k)
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
    }
