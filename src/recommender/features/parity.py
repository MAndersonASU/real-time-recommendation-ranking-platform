from recommender.features.online_features import RecentUserFeatures
from recommender.streaming.consumer import MAX_RECENT_ITEMS
from recommender.streaming.schema import EventType, InteractionEvent


def compute_recent_features_offline(
    events: list[InteractionEvent], user_id: str, cutoff: str
) -> RecentUserFeatures:
    """Recomputes one user's recent features directly from a raw event
    list, up to and including `cutoff`, using plain Python -- deliberately
    not calling anything in recommender.streaming.consumer. The whole
    point of a parity check is comparing two *independent*
    implementations of the same feature definition; reusing the online
    code here would make this test pass by construction and prove
    nothing about the online path actually being correct.

    ISO 8601 timestamps (as produced by replay_producer.py's
    `row.time.isoformat()`) sort correctly as plain strings, so no
    datetime parsing is needed to order events or compare against cutoff.
    """
    relevant = sorted(
        (e for e in events if e.user_id == user_id and e.timestamp <= cutoff),
        key=lambda e: e.timestamp,
    )
    clicks = [e for e in relevant if e.event_type is EventType.CLICK]
    impressions_seen = sum(1 for e in relevant if e.event_type is EventType.IMPRESSION)

    return RecentUserFeatures(
        user_id=user_id,
        recent_clicked_items=[e.item_id for e in clicks[-MAX_RECENT_ITEMS:]],
        impressions_seen=impressions_seen,
        clicks_seen=len(clicks),
        last_event_time=relevant[-1].timestamp if relevant else None,
    )
