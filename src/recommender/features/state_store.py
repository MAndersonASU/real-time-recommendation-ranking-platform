import json

import redis

from recommender.features.online_features import RecentUserFeatures

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
KEY_PREFIX = "recent_features:"
DEFAULT_TTL_SECONDS = 60 * 60 * 24  # a user with no new events in a day is stale, not "recent"

# Real, finite connect/read timeouts: without them, a Redis that hangs
# (not one that refuses the connection outright -- a network black
# hole, an overloaded instance not responding) would block a request
# indefinitely instead of raising the RedisError safe_recommend catches
# to fall back to popularity ranking. A slow, hanging dependency is a
# real failure mode distinct from an immediate connection-refused
# error, and the fallback path can only degrade gracefully from a
# failure it actually sees.
DEFAULT_SOCKET_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_SOCKET_TIMEOUT_SECONDS = 2.0


def build_client(
    redis_url: str = DEFAULT_REDIS_URL,
    socket_connect_timeout: float = DEFAULT_SOCKET_CONNECT_TIMEOUT_SECONDS,
    socket_timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
) -> redis.Redis:
    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=socket_connect_timeout,
        socket_timeout=socket_timeout,
    )


def _key(user_id: str) -> str:
    return f"{KEY_PREFIX}{user_id}"


def save_recent_features(
    client: redis.Redis, features: RecentUserFeatures, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> None:
    """Overwrites the full recent-feature record for one user as a single
    JSON string under one key, with an expiry -- a user who stops sending
    events should eventually fall out of the low-latency store on their
    own, rather than being served forever from a partial or ancient
    snapshot. A single JSON string, not a Redis hash, because every read
    of this key needs the whole record together and the value is small.
    """
    payload = json.dumps(
        {
            "user_id": features.user_id,
            "recent_clicked_items": list(features.recent_clicked_items),
            "impressions_seen": features.impressions_seen,
            "clicks_seen": features.clicks_seen,
            "last_event_time": features.last_event_time,
        }
    )
    client.set(_key(features.user_id), payload, ex=ttl_seconds)


def load_recent_features(client: redis.Redis, user_id: str) -> RecentUserFeatures | None:
    """Returns None for a user with no record -- either they've never sent
    an event, or their key has expired. Callers handle that None as a
    cold-start case (`docs/cold-start.md`), not an error.
    """
    raw = client.get(_key(user_id))
    if raw is None:
        return None
    data = json.loads(raw)
    return RecentUserFeatures(
        user_id=data["user_id"],
        recent_clicked_items=data["recent_clicked_items"],
        impressions_seen=data["impressions_seen"],
        clicks_seen=data["clicks_seen"],
        last_event_time=data["last_event_time"],
    )


PROCESSED_KEY_PREFIX = "processed_event:"
# Long enough to outlive any realistic restart-and-redelivery window,
# short enough that the marker set stays bounded on its own rather than
# growing forever the way an unbounded processed-id set would.
DEFAULT_PROCESSED_TTL_SECONDS = 60 * 60 * 24


def _processed_key(event_id: str) -> str:
    return f"{PROCESSED_KEY_PREFIX}{event_id}"


def claim_event(
    client: redis.Redis,
    event_id: str,
    features: RecentUserFeatures,
    ttl_seconds: int = DEFAULT_PROCESSED_TTL_SECONDS,
) -> RecentUserFeatures | None:
    """Atomically claims one event id for first-time processing, storing
    the resulting user state *inside the claim itself*.

    Returns None when the claim succeeded (this event has not been
    applied before). Returns the already-stored state when the event was
    already applied, so the caller can restore that instead of applying
    the event a second time.

    Why the state lives in the claim: a stream consumer mutates Redis
    and then commits a Kafka offset, and those are two separate
    operations. A crash between them redelivers the message after
    restart, and neither ordering of "mark processed" and "write state"
    is safe on its own -- marking first can lose the event's effect,
    writing first can apply it twice, and an in-process dedup set does
    not survive the restart at all. Carrying the state in the claim
    makes a single atomic `SET NX` the only operation that has to
    succeed: a redelivery finds the claim, recovers the exact state that
    event produced, and repairs the state key rather than re-applying
    anything.
    """
    payload = json.dumps(
        {
            "user_id": features.user_id,
            "recent_clicked_items": list(features.recent_clicked_items),
            "impressions_seen": features.impressions_seen,
            "clicks_seen": features.clicks_seen,
            "last_event_time": features.last_event_time,
        }
    )
    claimed = client.set(_processed_key(event_id), payload, nx=True, ex=ttl_seconds)
    if claimed:
        return None

    existing = client.get(_processed_key(event_id))
    if existing is None:
        # The claim expired between the SET and this GET. Treating it as
        # a fresh claim is the safe read: re-applying a day-old event is
        # a bounded error, silently dropping it is not.
        return None
    data = json.loads(existing)
    return RecentUserFeatures(
        user_id=data["user_id"],
        recent_clicked_items=data["recent_clicked_items"],
        impressions_seen=data["impressions_seen"],
        clicks_seen=data["clicks_seen"],
        last_event_time=data["last_event_time"],
    )
