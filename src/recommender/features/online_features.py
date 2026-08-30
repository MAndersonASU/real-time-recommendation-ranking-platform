from dataclasses import dataclass

import pandas as pd

from recommender.ranking.features import dominant_category, history_ids_from_raw
from recommender.retrieval.features import MAX_HISTORY
from recommender.streaming.consumer import UserState


@dataclass(frozen=True)
class DurableUserFeatures:
    """Computed offline, in a batch job, from a user's full history up to
    some cutoff. Refreshed occasionally rather than per-event -- serving a
    slightly stale copy of these is an acceptable, deliberate tradeoff.

    `history_item_ids` (SERVING-DURABLE-HISTORY-69) is the last
    `MAX_HISTORY` *valid catalog* article ids from this user's own
    point-in-time history, in original order -- a bounded, retrieval-
    ready history the live path can fall back on when Redis has no
    recent record for a returning user. Before this field existed, the
    live retrieval query used only `recent_clicked_items` from Redis:
    a returning user with a genuinely healthy but empty Redis record
    (not an outage -- simply no live event yet) produced an empty
    `history_ids`, a zero-norm two-tower user vector, and the same
    global-popularity candidate pool as every other such user, even
    though their real durable history was sitting right here the whole
    time. Defaults to an empty tuple so every existing construction
    site that predates this field keeps working unchanged.
    """

    user_id: str
    dominant_category: str | None
    lifetime_click_count: int
    history_item_ids: tuple[str, ...] = ()


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

    # Two defects this ordering fixes, both reproduced before changing:
    #
    # 1. Sorting on `time` alone left impressions sharing a timestamp in
    #    source order, so shuffling the input changed a user's features --
    #    the same data produced dominant_category 'news' or 'sports'
    #    depending on row order. impression_id is an immutable secondary
    #    key, so the choice is now deterministic.
    #
    # 2. `.last()` operates column-wise, taking the last *non-null* value
    #    in each column independently. A user whose latest impression had
    #    no history inherited the history from an earlier row, reporting
    #    3 lifetime clicks where the point-in-time answer was 0. Selecting
    #    whole rows by position keeps every field from one impression.
    sort_keys = ["time", "impression_id"] if "impression_id" in behaviors.columns else ["time"]
    ordered = behaviors.sort_values(sort_keys, kind="mergesort")
    latest = ordered.groupby("user_id", sort=False).tail(1).set_index("user_id")

    result = {}
    for user_id, row in latest.iterrows():
        raw_history = row["history"]
        history_ids = history_ids_from_raw(raw_history) if isinstance(raw_history, str) else []
        # Bounded to the same MAX_HISTORY the live recent-feature store
        # caps at, and filtered to ids this catalog actually has content
        # for (an unknown id would encode to nothing in
        # encode_recent_history anyway, so keeping it here would only
        # inflate history_item_ids with dead weight) -- the last
        # MAX_HISTORY valid ones, in original order, since a two-tower
        # embedding built from a user's most recent clicks is the
        # closest offline stand-in for what a live recent-click history
        # would have looked like.
        valid_history_ids = [nid for nid in history_ids if nid in category_by_id.index]
        result[user_id] = DurableUserFeatures(
            user_id=user_id,
            dominant_category=dominant_category(history_ids, category_by_id),
            lifetime_click_count=len(history_ids),
            history_item_ids=tuple(valid_history_ids[-MAX_HISTORY:]),
        )
    return result


def recent_features_from_user_state(user_id: str, state: UserState) -> RecentUserFeatures:
    """Adapts the streaming consumer's in-process UserState into the RecentUserFeatures
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


def user_state_from_recent_features(features: RecentUserFeatures) -> UserState:
    """The reverse of `recent_features_from_user_state` -- restores a
    real `UserState` from a durable `RecentUserFeatures` record, so a
    restarted stream consumer can resume from real prior state instead
    of silently starting empty and overwriting it on the next event
    (the real restart-corruption bug this function exists to fix).
    """
    state = UserState(
        impressions_seen=features.impressions_seen,
        clicks_seen=features.clicks_seen,
        last_event_time=features.last_event_time,
    )
    state.recent_clicked_items.extend(features.recent_clicked_items)
    return state
