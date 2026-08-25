import redis

from recommender.features.online_features import (
    recent_features_from_user_state,
    user_state_from_recent_features,
)
from recommender.features.state_store import (
    claim_and_apply_event,
    current_state_version,
    load_recent_features,
)
from recommender.streaming.consumer import StreamConsumer, UserState

# Redis-level status codes returned by `claim_and_apply_event`.
_APPLIED = 1
_DUPLICATE = 0
# Bounded: a conflict means a competing writer won, which should
# resolve within a couple of attempts. An unbounded retry would spin
# forever against a persistently conflicting writer.
_MAX_VERSION_CONFLICT_RETRIES = 5


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

    def _on_state_updated(self, user_id: str, state: UserState, event_id: str) -> bool:
        """Claims the event and writes the resulting state atomically.

        Two distinct failures are prevented here, and they pull in
        opposite directions:

        - A crash between the Redis write and the Kafka offset commit
          redelivers the message. Applying it again double-counts.
        - Refusing a duplicate by restoring the state stored *with* that
          event rolls the user backwards, discarding every event applied
          since. That is strictly worse than the double count: it loses
          real data rather than inflating it.

        So a duplicate returns the user's *current* state, never a
        historical snapshot, and the claim and the state write happen in
        one atomic step so neither can land without the other.

        A version conflict means another writer advanced this user's
        state between the read and the write. The event is re-derived
        against the newer state and retried rather than overwriting it.
        """
        for _attempt in range(_MAX_VERSION_CONFLICT_RETRIES):
            expected_version = current_state_version(self._redis_client, user_id)
            features = recent_features_from_user_state(user_id, state)
            status, stored = claim_and_apply_event(
                self._redis_client, event_id, features, expected_version
            )

            if status == _APPLIED:
                return True

            if status == _DUPLICATE:
                # Already applied. Adopt the current state -- not the
                # state this event originally produced -- so nothing
                # applied since is lost.
                if stored is not None:
                    self.user_states[user_id] = user_state_from_recent_features(stored)
                return False

            # Version conflict: rebuild this event's effect on top of the
            # state that actually won, then try again.
            if stored is None:
                break
            self.user_states[user_id] = user_state_from_recent_features(stored)
            state = self._reapply(self.user_states[user_id], state)

        raise RuntimeError(
            f"could not apply event {event_id} for a user after "
            f"{_MAX_VERSION_CONFLICT_RETRIES} version conflicts"
        )

    @staticmethod
    def _reapply(current: UserState, attempted: UserState) -> UserState:
        """Re-derives the attempted event's effect on top of newer state.

        Only the last click and the counters the event contributed are
        carried over; everything else comes from the state that won, so
        a retry never resurrects stale history.
        """
        if attempted.recent_clicked_items:
            current.recent_clicked_items.append(attempted.recent_clicked_items[-1])
            current.clicks_seen += 1
        else:
            current.impressions_seen += 1
        current.last_event_time = attempted.last_event_time
        return current
