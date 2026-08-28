import json
import time

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.features.online_features import RecentUserFeatures

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
KEY_PREFIX = "recent_features:"
DEFAULT_TTL_SECONDS = 60 * 60 * 24  # a user with no new events in a day is stale, not "recent"

# Real, finite connect/read timeouts: without them, a Redis that hangs
# (not one that refuses the connection outright -- a network black
# hole, an overloaded instance not responding) would block a request
# indefinitely instead of raising the RedisError the online feature
# lookup catches to degrade gracefully. A slow, hanging dependency is a
# real failure mode distinct from an immediate connection-refused
# error, and a degraded response can only be produced from a failure
# actually seen.
#
# 0.2s, not the earlier 2.0s: `docs/operations/state-store.md` measured
# real read latency at 0.29 ms p50 / 1.12 ms p99 against a healthy
# container, so 200ms is already ~180x that p99 -- generous headroom
# for jitter, nowhere close to what a request's own latency budget
# (`docs/operations/inference-path.md`'s ~61ms p99 end-to-end) can absorb.
DEFAULT_SOCKET_CONNECT_TIMEOUT_SECONDS = 0.2
DEFAULT_SOCKET_TIMEOUT_SECONDS = 0.2


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
        # Explicit, not left to redis-py's own default: that default
        # retries a connection error once with a backoff delay, which
        # silently doubled a real failed lookup against a genuinely
        # unreachable host from this client's own 2-second timeout to
        # just over 4 seconds -- found by timing `build_client()` against
        # a dead port, not assumed. A caller here needs to know it failed
        # fast, not have that already-short timeout multiplied under it
        # by a policy nothing in this module ever chose.
        retry=Retry(NoBackoff(), 0),
        retry_on_error=[],
    )


class RedisCircuitBreaker:
    """Trips after `failure_threshold` consecutive Redis failures and
    stays open for `cooldown_seconds` -- so once Redis is genuinely
    down, requests after the first few fail fast without even
    attempting a connection, instead of every concurrent request paying
    its own connect timeout against a host that is not coming back
    within it. One probe request is let through once the cooldown
    elapses, to detect recovery without waiting for an operator.

    Shared across requests: one instance lives on `ServingContext`
    (`recommender.serving.pipeline`), built once at service start, not
    per request.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 5.0,
        clock=time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def allow_request(self) -> bool:
        if self._opened_at is None:
            return True
        return (self._clock() - self._opened_at) >= self._cooldown_seconds

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._opened_at = self._clock()

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None and not self.allow_request()


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
    cold-start case (`docs/experiments/cold-start.md`), not an error.
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


# Atomically claim one event and apply its delta to whatever state is
# current *inside the script*.
#
# The earlier version took a fully-formed state computed by the caller
# and wrote it under a version check. That still lost updates: two
# consumers both reading empty state each computed a complete state from
# their own stale basis, and the version check only guarded the stored
# value, not the basis the new value was derived from. Whichever wrote
# second silently erased the other's event.
#
# Applying the delta to state loaded within the script removes the stale
# basis entirely -- there is nothing for the caller to compute from.
#
# Returns {status, state_json}:
#   0 = duplicate -> state_json is the CURRENT state. Returning the
#       state stored with the original event would roll the user back,
#       discarding everything applied since.
#   1 = applied
_CLAIM_AND_APPLY_LUA = """
local claim_key = KEYS[1]
local state_key = KEYS[2]
local user_id = ARGV[1]
local event_type = ARGV[2]
local item_id = ARGV[3]
local event_time = ARGV[4]
local max_history = tonumber(ARGV[5])
local claim_ttl = tonumber(ARGV[6])
local state_ttl = tonumber(ARGV[7])

if redis.call('EXISTS', claim_key) == 1 then
  return {0, redis.call('GET', state_key) or ''}
end

local state
local raw = redis.call('GET', state_key)
if raw then
  local ok, decoded = pcall(cjson.decode, raw)
  if ok then state = decoded end
end
if not state then
  state = {user_id = user_id, recent_clicked_items = {},
           impressions_seen = 0, clicks_seen = 0, last_event_time = false}
end
if not state['recent_clicked_items'] then state['recent_clicked_items'] = {} end

if event_type == 'click' then
  state['clicks_seen'] = (tonumber(state['clicks_seen']) or 0) + 1
  table.insert(state['recent_clicked_items'], item_id)
  while #state['recent_clicked_items'] > max_history do
    table.remove(state['recent_clicked_items'], 1)
  end
else
  state['impressions_seen'] = (tonumber(state['impressions_seen']) or 0) + 1
end
state['last_event_time'] = event_time
state['version'] = (tonumber(state['version']) or 0) + 1

-- An empty Lua table encodes as {} rather than []; force array shape so
-- the round trip stays a list.
if #state['recent_clicked_items'] == 0 then
  state['recent_clicked_items'] = setmetatable({}, cjson.array_mt)
end

local encoded = cjson.encode(state)
redis.call('SET', claim_key, '1', 'EX', claim_ttl)
redis.call('SET', state_key, encoded, 'EX', state_ttl)
return {1, encoded}
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
    user_id: str,
    event_type: str,
    item_id: str,
    event_time: str | None,
    max_history: int,
    ttl_seconds: int = DEFAULT_PROCESSED_TTL_SECONDS,
    state_ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[int, RecentUserFeatures | None]:
    """Claims one event and applies its effect to the user's current
    state in a single atomic step.

    Takes the event's own fields rather than a caller-computed state, so
    there is no stale local snapshot that a concurrent writer could
    overwrite. Returns `(status, state)` where status is 1 when newly
    applied and 0 when already applied -- in which case `state` is the
    user's current state, never the state stored with the original
    delivery.
    """
    status, raw = client.eval(  # type: ignore[union-attr]
        _CLAIM_AND_APPLY_LUA,
        2,
        _processed_key(event_id),
        _key(user_id),
        user_id,
        event_type,
        item_id,
        event_time or "",
        str(max_history),
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
        recent_clicked_items=list(data.get("recent_clicked_items") or []),
        impressions_seen=int(data.get("impressions_seen") or 0),
        clicks_seen=int(data.get("clicks_seen") or 0),
        last_event_time=data.get("last_event_time") or None,
    )
