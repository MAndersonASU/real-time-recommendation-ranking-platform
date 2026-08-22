import pandas as pd

from recommender.data.mind import explode_impressions

# Chosen from real measurement (docs/reranking-freshness.md): at a 0.5-day
# (12-hour) threshold, 36.3% of all validation candidate rows count as
# fresh and only 0.7% of impressions have zero fresh candidates available
# at all -- common enough that a quota is almost always satisfiable,
# scarce enough that it means something.
DEFAULT_FRESH_THRESHOLD_DAYS = 0.5
DEFAULT_MIN_FRESH_IN_SLATE = 2


def compute_first_seen(train: pd.DataFrame, exploded: pd.DataFrame | None = None) -> pd.Series:
    """Earliest impression time at which each item appears as a candidate
    in `train` -- the only per-item timestamp signal this dataset has at
    all. `news.tsv` carries no publish date (already found in
    docs/ranking-features.md), and a `history` entry carries no timestamp
    of its own; only the surrounding impression's own time does.

    `exploded` lets a caller that already has `explode_impressions(train)`
    (e.g. `recommender.serving.pipeline.build_serving_context`, which also
    needs it for `compute_popularity`) pass it straight through instead of
    this function re-deriving its own copy of the same multi-million-row
    frame (docs/profile-hotspots.md).
    """
    exploded = exploded if exploded is not None else explode_impressions(train)
    return exploded.groupby("news_id")["time"].min()


def compute_age_days(candidates: pd.DataFrame, impression_time, first_seen: pd.Series) -> pd.Series:
    """Days between this impression and an item's first observed
    appearance in train. An item absent from `first_seen` has never been
    observed before at all -- treated as age 0 (maximally fresh), not a
    missing value, since "never seen before" is itself the strongest
    freshness signal this dataset can offer.
    """
    first_seen_time = candidates["news_id"].map(first_seen)
    age = (impression_time - first_seen_time).dt.total_seconds() / 86400
    return age.fillna(0.0).clip(lower=0.0)


def apply_freshness_quota(
    slate: pd.DataFrame,
    candidates: pd.DataFrame,
    score_column: str,
    age_column: str = "age_days",
    min_fresh_in_slate: int = DEFAULT_MIN_FRESH_IN_SLATE,
    fresh_threshold_days: float = DEFAULT_FRESH_THRESHOLD_DAYS,
) -> pd.DataFrame:
    """If `slate` has fewer than `min_fresh_in_slate` items with
    age_days <= fresh_threshold_days, swaps in the best-scored fresh
    candidates not already in the slate, replacing the slate's
    lowest-scored non-fresh items first. A transparent quota, not a soft
    score boost: exactly how many fresh items end up in the slate is a
    known, guaranteed number, not an indirect side effect of reweighting.
    Applied after diversity (`diversity.py`) as a separate, independently
    testable pass -- it does not re-check the category cap on a swap-in,
    a disclosed simplification, not an oversight.
    """
    slate = slate.copy()
    is_fresh_in_slate = slate[age_column] <= fresh_threshold_days
    needed = min_fresh_in_slate - int(is_fresh_in_slate.sum())
    if needed <= 0:
        return slate

    in_slate_ids = set(slate["news_id"])
    fresh_pool = candidates[
        (candidates[age_column] <= fresh_threshold_days) & (~candidates["news_id"].isin(in_slate_ids))
    ].sort_values(score_column, ascending=False)

    swap_in = fresh_pool.head(needed)
    if swap_in.empty:
        return slate  # no fresh alternative exists among the candidates at all

    # Give up relevance starting from the slate's least valuable non-fresh
    # items first.
    replaceable = slate[~is_fresh_in_slate].sort_values(score_column, ascending=True)
    drop_ids = set(replaceable["news_id"].head(len(swap_in)))

    remaining = slate[~slate["news_id"].isin(drop_ids)]
    result = pd.concat([remaining, swap_in], ignore_index=True)
    return result.sort_values(score_column, ascending=False).reset_index(drop=True)
