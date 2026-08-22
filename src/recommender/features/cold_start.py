from dataclasses import dataclass

import redis

from recommender.features.online_features import DurableUserFeatures, RecentUserFeatures
from recommender.features.state_store import load_recent_features

DEFAULT_DURABLE_FEATURES = DurableUserFeatures(
    user_id="", dominant_category=None, lifetime_click_count=0
)
DEFAULT_RECENT_FEATURES = RecentUserFeatures(
    user_id="", recent_clicked_items=[], impressions_seen=0, clicks_seen=0, last_event_time=None
)


@dataclass(frozen=True)
class OnlineFeatureLookup:
    """The combined durable + recent feature view for one user, plus two
    flags recording whether either half was a genuine cold-start fallback
    rather than a real, found value -- callers that care about the
    distinction (offline evaluation, monitoring) can check these instead
    of trying to infer it from the values themselves, since a real user
    can legitimately have zero lifetime clicks or an empty recent list.
    """

    durable: DurableUserFeatures
    recent: RecentUserFeatures
    durable_is_fallback: bool
    recent_is_fallback: bool


def get_online_features(
    user_id: str,
    durable_features_by_user: dict[str, DurableUserFeatures],
    redis_client: redis.Redis,
    use_recent_features: bool = True,
) -> OnlineFeatureLookup:
    """Looks up both halves of a user's online features independently,
    since they can be missing for different, unrelated reasons: a user
    absent from `durable_features_by_user` was never seen in the offline
    training history at all (a genuinely new user), while a user with no
    Redis record has simply not sent a live event yet (or their record
    expired) -- a user can be one without being the other, e.g. a
    long-time user whose session just started, or a brand new user who
    is already actively clicking. Neither case raises; both fall back to
    an explicit, neutral default instead.

    `use_recent_features=False` skips the Redis lookup entirely and
    always falls back to the same neutral default -- the recent-
    streaming-features ablation (docs/ablations.md), simulating a system
    with no live Kafka/Redis feed at all rather than merely an empty one.
    """
    durable = durable_features_by_user.get(user_id)
    recent = load_recent_features(redis_client, user_id) if use_recent_features else None

    return OnlineFeatureLookup(
        durable=durable if durable is not None else DEFAULT_DURABLE_FEATURES,
        recent=recent if recent is not None else DEFAULT_RECENT_FEATURES,
        durable_is_fallback=durable is None,
        recent_is_fallback=recent is None,
    )
