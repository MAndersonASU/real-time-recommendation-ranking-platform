from dataclasses import dataclass

import pandas as pd

from recommender.ranking.features import dominant_category, history_ids_from_raw
from recommender.streaming.consumer import UserState


@dataclass(frozen=True)
class DurableUserFeatures:
    """Computed offline, in a batch job, from a user's full history up to
    some cutoff. Refreshed occasionally rather than per-event -- serving a
    slightly stale copy of these is an acceptable, deliberate tradeoff.
    """

    user_id: str
    dominant_category: str | None
    lifetime_click_count: int


@dataclass
class RecentUserFeatures:
    """Must reflect the very latest events. This is the formal contract
    around what recommender.streaming.consumer.UserState already tracks
    per user -- see recent_features_from_user_state below.
    """

    user_id: str
    recent_clicked_items: list
    impressions_seen: int
    clicks_seen: int
    last_event_time: str | None


def compute_durable_features(
    behaviors: pd.DataFrame, news: pd.DataFrame
) -> dict[str, DurableUserFeatures]:
    """One DurableUserFeatures per user, built from each user's most recent
    impression's `history` field -- MIND already records, per impression,
    the user's click history up to that point, so their latest impression
    carries the longest available history for that user in this split.
    Reuses dominant_category and history_ids_from_raw from ranking/features.py
    rather than recomputing the same logic a second way.
    """
    category_by_id = news.set_index("news_id")["category"]
    latest = behaviors.sort_values("time").groupby("user_id").last()

    result = {}
    for user_id, row in latest.iterrows():
        history_ids = history_ids_from_raw(row["history"])
        result[user_id] = DurableUserFeatures(
            user_id=user_id,
            dominant_category=dominant_category(history_ids, category_by_id),
            lifetime_click_count=len(history_ids),
        )
    return result


def recent_features_from_user_state(user_id: str, state: UserState) -> RecentUserFeatures:
    """Adapts Phase 6's in-process UserState into the RecentUserFeatures
    contract, so callers depend on a stable feature shape instead of the
    streaming consumer's internal state representation directly.
    """
    return RecentUserFeatures(
        user_id=user_id,
        recent_clicked_items=list(state.recent_clicked_items),
        impressions_seen=state.impressions_seen,
        clicks_seen=state.clicks_seen,
        last_event_time=state.last_event_time,
    )
