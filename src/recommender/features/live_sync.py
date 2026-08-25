import redis

from recommender.features.online_features import (
    user_state_from_recent_features,
)
from recommender.features.state_store import claim_and_apply_event, load_recent_features
from recommender.streaming.consumer import StreamConsumer, UserState

# Redis-level status codes returned by `claim_and_apply_event`.
_DUPLICATE = 0
# Bounded: a conflict means a competing writer won, which should
# resolve within a couple of attempts. An unbounded retry would spin
# forever against a persistently conflicting writer.
# The recent-click window the streaming state keeps per user.
MAX_RECENT_CLICKS = 20


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
        """Not used by this consumer -- see `_apply_event`.

        The base class calls this after mutating its own in-process
        state, which is exactly the stale basis that must not reach
        Redis. This subclass overrides `process` instead, so state is
        only ever derived inside the atomic script.
        """
        return True

    def process(self, raw) -> bool:
        """Applies one event by handing its own fields to the atomic
        claim-and-apply, rather than computing a state locally first.

        Three failures are prevented, and they pull against each other:

        - A crash between the Redis write and the Kafka offset commit
          redelivers the message; applying it again double-counts.
        - Refusing a duplicate by restoring the state stored *with* that
          event rolls the user backwards, discarding everything applied
          since -- worse than the double count, because it loses data.
        - Two consumers each deriving a complete state from their own
          stale read overwrite one another, silently losing an event.

        Handing the event's fields to a script that loads current state
        itself removes the third entirely: there is no local basis to go
        stale.
        """
        event = self.parse(raw)
        if event is None:
            return False
        if event.event_id in self._seen_event_ids:
            self.counters.duplicates_skipped += 1
            return False
        self._seen_event_ids.add(event.event_id)

        status, stored = claim_and_apply_event(
            self._redis_client,
            event.event_id,
            event.user_id,
            event.event_type.value,
            event.item_id,
            event.timestamp,
            MAX_RECENT_CLICKS,
        )

        if stored is not None:
            self.user_states[event.user_id] = user_state_from_recent_features(stored)

        if status == _DUPLICATE:
            self.counters.duplicates_skipped += 1
            return False

        self.counters.events_by_type[event.event_type.value] = (
            self.counters.events_by_type.get(event.event_type.value, 0) + 1
        )
        self.counters.distinct_users.add(event.user_id)
        self.counters.distinct_items.add(event.item_id)
        self.counters.total_processed += 1
        return True
