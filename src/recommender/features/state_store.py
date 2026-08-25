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
    # Carries a monotonic version so `claim_and_apply_event` can reject a
    # write computed from state that has since moved on.
    version = current_state_version(client, features.user_id) + 1
    client.set(_key(features.user_id), _state_payload(features, version), ex=ttl_seconds)


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
# growing forever the way an unbounded processed-id set would. This is
# the boundary of the idempotency guarantee, not an implementation
# detail: a redelivery arriving later than this is treated as new.
DEFAULT_PROCESSED_TTL_SECONDS = 60 * 60 * 24


def _processed_key(event_id: str) -> str:
    return f"{PROCESSED_KEY_PREFIX}{event_id}"


# Atomically: refuse an already-claimed event, reject a stale write, or
# claim the event and store the new state together.
#
# Redis runs a script atomically, so no interleaving consumer can land
# between the duplicate check, the version check and the write. Doing
# these as separate commands leaves two real failure windows: a crash
# between claim and write silently drops the event's effect, and two
# consumers reading the same state concurrently overwrite each other.
#
# Returns {status, state_json}:
#   0 = duplicate  -> state_json is the CURRENT state, not the state that
#                     existed when the event was first applied. Returning
#                     the historical snapshot is what allowed a late
#                     duplicate to roll a user's state backwards and lose
#                     every event applied since.
#   1 = applied
#   2 = version conflict -> caller reloads and retries
_CLAIM_AND_APPLY_LUA = """
local claim_key = KEYS[1]
local state_key = KEYS[2]
local new_state = ARGV[1]
local expected_version = tonumber(ARGV[2])
local claim_ttl = tonumber(ARGV[3])
local state_ttl = tonumber(ARGV[4])

if redis.call('EXISTS', claim_key) == 1 then
  return {0, redis.call('GET', state_key) or ''}
end

local current = redis.call('GET', state_key)
local current_version = 0
if current then
  local ok, decoded = pcall(cjson.decode, current)
  if ok and decoded['version'] then current_version = tonumber(decoded['version']) end
end

if current_version ~= expected_version then
  return {2, current or ''}
end

redis.call('SET', claim_key, '1', 'EX', claim_ttl)
redis.call('SET', state_key, new_state, 'EX', state_ttl)
return {1, new_state}
"""


def _state_payload(features: RecentUserFeatures, version: int) -> str:
    return json.dumps(
        {
            "user_id": features.user_id,
            "recent_clicked_items": list(features.recent_clicked_items),
            "impressions_seen": features.impressions_seen,
            "clicks_seen": features.clicks_seen,
            "last_event_time": features.last_event_time,
            "version": version,
        }
    )


def current_state_version(client: redis.Redis, user_id: str) -> int:
    raw = client.get(_key(user_id))
    if raw is None:
        return 0
    try:
        return int(json.loads(raw).get("version", 0))
    except (ValueError, TypeError):
        return 0


def claim_and_apply_event(
    client: redis.Redis,
    event_id: str,
    features: RecentUserFeatures,
    expected_version: int,
    ttl_seconds: int = DEFAULT_PROCESSED_TTL_SECONDS,
    state_ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[int, RecentUserFeatures | None]:
    """Claims one event and writes the resulting state in a single atomic
    step, or reports why it did not.

    Returns `(status, state)` where status is 1 when the event was newly
    applied, 0 when it was already applied (and `state` is the user's
    *current* state), and 2 when another writer advanced the state first
    (and `state` is that newer state, for the caller to retry against).
    """
    payload = _state_payload(features, expected_version + 1)
    status, raw = client.eval(  # type: ignore[union-attr]
        _CLAIM_AND_APPLY_LUA,
        2,
        _processed_key(event_id),
        _key(features.user_id),
        payload,
        str(expected_version),
        str(ttl_seconds),
        str(state_ttl_seconds),
    )
    status = int(status)
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not raw:
        return status, None
    data = json.loads(raw)
    return status, RecentUserFeatures(
        user_id=data["user_id"],
        recent_clicked_items=data["recent_clicked_items"],
        impressions_seen=data["impressions_seen"],
        clicks_seen=data["clicks_seen"],
        last_event_time=data["last_event_time"],
    )
