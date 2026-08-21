import redis

from recommender.features.online_features import recent_features_from_user_state
from recommender.features.state_store import save_recent_features
from recommender.streaming.consumer import StreamConsumer, UserState


class SyncingStreamConsumer(StreamConsumer):
    """A StreamConsumer that also writes each touched user's recent
    features straight through to Redis, the moment their in-process state
    changes -- so the same event that updates Phase 6's in-memory state
    also updates the low-latency store any other process would actually
    read recent features from. Overrides only the `_on_state_updated`
    hook; parsing, dedup, and counting are untouched, inherited as-is.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        super().__init__()
        self._redis_client = redis_client

    def _on_state_updated(self, user_id: str, state: UserState) -> None:
        save_recent_features(
            self._redis_client, recent_features_from_user_state(user_id, state)
        )
