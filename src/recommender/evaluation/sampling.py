"""Deterministic, representative sampling for bounded evaluations.

Several comparisons are too expensive to run over every impression, so
they run over a sample. That sample used to be `head(N)`, which is not a
sample at all: it takes the earliest qualifying impressions, so every
conclusion was drawn from one narrow slice of the time window and from
whichever users happened to be active in it.

Sampling here is seeded rather than random-per-run, so a rerun of the
same commit against the same data selects the same impressions and the
comparison is reproducible. The selection is also described -- seed,
eligible population, time range, user count and a digest of the chosen
ids -- so a report states what it measured rather than only how many.
"""

import hashlib

import numpy as np
import pandas as pd

DEFAULT_SAMPLE_SEED = 20260825


def sample_impression_ids(
    frame: pd.DataFrame,
    size: int,
    seed: int = DEFAULT_SAMPLE_SEED,
    id_column: str = "impression_id",
) -> pd.Index:
    """Selects up to `size` impression ids uniformly at random, seeded.

    Uniform rather than stratified: the eligible population here is a
    single day's impressions, so there is no natural stratum that a
    uniform draw would systematically under-cover. Sorting the result
    keeps downstream iteration order stable regardless of draw order.
    """
    eligible = pd.Index(frame[id_column].drop_duplicates())
    if len(eligible) <= size:
        return eligible.sort_values()

    rng = np.random.default_rng(seed)
    chosen = rng.choice(eligible.to_numpy(), size=size, replace=False)
    return pd.Index(chosen).sort_values()


def describe_sample(
    frame: pd.DataFrame,
    selected_ids: pd.Index,
    seed: int = DEFAULT_SAMPLE_SEED,
    id_column: str = "impression_id",
    time_column: str = "time",
    user_column: str = "user_id",
) -> dict:
    """Describes a selection well enough to interpret and reproduce it.

    The digest of the selected ids matters: it lets a later run confirm
    it drew the same sample without publishing the ids themselves, which
    would leak dataset content.
    """
    selected = frame[frame[id_column].isin(selected_ids)]
    eligible_count = int(frame[id_column].nunique())

    description = {
        "method": "seeded uniform random without replacement",
        "seed": seed,
        "eligible_impressions": eligible_count,
        "selected_impressions": len(selected_ids),
        "selected_fraction": (len(selected_ids) / eligible_count) if eligible_count else None,
        "selected_ids_sha256": hashlib.sha256(
            ",".join(str(i) for i in sorted(selected_ids)).encode()
        ).hexdigest()[:16],
    }

    if user_column in selected.columns:
        description["distinct_users"] = int(selected[user_column].nunique())
    if time_column in selected.columns and not selected.empty:
        times = pd.to_datetime(selected[time_column], errors="coerce")
        description["time_range"] = {
            "start": str(times.min()),
            "end": str(times.max()),
        }
    return description
