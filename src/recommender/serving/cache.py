from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from recommender.features.online_features import DurableUserFeatures, compute_durable_features

DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60.0  # matches Phase 7's stated "refreshed daily" design intent


@dataclass
class DurableFeatureCache:
    """Durable features (docs/online-features.md) are computed offline and
    meant to be refreshed occasionally, not per request -- but "loaded
    once at service start and never checked again" has no actual
    freshness rule behind it, just an accident of when the process last
    restarted. This wraps the lookup dict with an explicit timestamp and
    a named staleness threshold, so "is this still fresh enough" is a
    real, checkable question instead of an assumption.

    Deliberately does not refresh itself inside a request: recomputing
    durable features means re-reading a real offline split and rebuilding
    the whole dict, which is exactly the kind of expensive, batch-shaped
    work a live request path should never trigger inline. `is_stale`
    exists so a caller (a scheduled job, an operator, a monitoring check)
    can decide when to call `refresh` -- this cache reports staleness, it
    does not silently fix it.
    """

    features_by_user: dict[str, DurableUserFeatures]
    computed_at: datetime
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS

    def get(self, user_id: str) -> DurableUserFeatures | None:
        return self.features_by_user.get(user_id)

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now if now is not None else datetime.now()  # noqa: DTZ005 -- naive, matches every other timestamp in this project
        return (now - self.computed_at).total_seconds() > self.max_age_seconds


def build_durable_feature_cache(
    behaviors: pd.DataFrame, news: pd.DataFrame, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> DurableFeatureCache:
    return DurableFeatureCache(
        features_by_user=compute_durable_features(behaviors, news),
        computed_at=datetime.now(),  # noqa: DTZ005 -- naive, matches every other timestamp in this project
        max_age_seconds=max_age_seconds,
    )


def refresh(cache: DurableFeatureCache, behaviors: pd.DataFrame, news: pd.DataFrame) -> DurableFeatureCache:
    """Recomputes the cache from fresh data and stamps a new
    `computed_at` -- returns a new cache rather than mutating in place,
    so a caller holding a reference to the old one still sees a
    consistent snapshot rather than values changing under it mid-read.
    """
    return build_durable_feature_cache(behaviors, news, max_age_seconds=cache.max_age_seconds)
