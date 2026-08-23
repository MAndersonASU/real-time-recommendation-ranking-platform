import redis

from recommender.features.online_features import (
    recent_features_from_user_state,
    user_state_from_recent_features,
)
from recommender.features.state_store import load_recent_features, save_recent_features
from recommender.streaming.consumer import StreamConsumer, UserState


class SyncingStreamConsumer(StreamConsumer):
    """A StreamConsumer that also writes each touched user's recent
    features straight through to Redis, the moment their in-process state
    changes -- so the same event that updates Phase 6's in-memory state
    also updates the low-latency store any other process would actually
    read recent features from. Overrides `_on_state_updated` (write path)
    and `_get_or_create_state` (read/restore path); parsing, dedup, and
    counting are untouched, inherited as-is.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        super().__init__()
        self._redis_client = redis_client

    def _get_or_create_state(self, user_id: str) -> UserState:
        """Restores real prior state from Redis the first time this
        process touches a user, instead of defaulting to an empty
        `UserState` -- a fresh process (after a restart) has no
        in-process history for anyone, but Redis might already hold a
        real record for this user from before the restart. Without
        this override, the first event after a restart would create an
        empty state and `_on_state_updated` would overwrite the real
        Redis record with it (the real bug this class previously had).
        """
        if user_id in self.user_states:
            return self.user_states[user_id]
        existing = load_recent_features(self._redis_client, user_id)
        state = user_state_from_recent_features(existing) if existing is not None else UserState()
        self.user_states[user_id] = state
        return state

    def _on_state_updated(self, user_id: str, state: UserState) -> None:
        save_recent_features(
            self._redis_client, recent_features_from_user_state(user_id, state)
        )
