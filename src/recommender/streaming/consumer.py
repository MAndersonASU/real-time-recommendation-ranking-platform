import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from confluent_kafka import KafkaException

from recommender.monitoring.metrics import COMMIT_FAILURES
from recommender.streaming.kafka_client import DEFAULT_BOOTSTRAP_SERVERS, build_consumer
from recommender.streaming.replay_producer import TOPIC
from recommender.streaming.schema import SCHEMA_VERSION, EventType, InteractionEvent

MAX_RECENT_ITEMS = 20

# `_seen_event_ids`, the monitoring counters' `distinct_users`/
# `distinct_items`, and `user_states` (below) are all bounded to a fixed
# capacity, evicting the oldest entry once full -- a plain, unbounded
# `set` or `dict` would let a long-running consumer process grow them
# forever, one entry per never-before-seen event id, user, or item, for
# as long as the process runs. A disclosed, intentional tradeoff, not a
# full fix for the underlying problem: `distinct_users`/`distinct_items`
# now mean "distinct among the most recently tracked
# `MAX_DISTINCT_TRACKED` entries," not "distinct across this process's
# entire lifetime" -- and duplicate detection only catches a redelivery
# that arrives within the same window. A durable, cross-restart dedup
# store is a materially larger change (the same tradeoff already named
# for these counters resetting across restarts) and out of scope here;
# this only fixes the unbounded in-process memory growth.
MAX_SEEN_EVENT_IDS = 100_000
MAX_DISTINCT_TRACKED = 100_000

# For SyncingStreamConsumer, `user_states` is a read-through cache over
# Redis, which stays authoritative -- an evicted entry is just reloaded
# from Redis on that user's next event, nothing is lost. For the plain
# in-process StreamConsumer, it is the only copy of that state, so
# eviction here is a real, permanent loss of a user's recent history;
# that class is scoped to finite verification runs (see its docstring),
# never wired into a long-running production entrypoint, so this bound
# exists to cap worst-case memory rather than to be exercised in
# practice.
MAX_TRACKED_USERS = 100_000

# Bounded retry for an offset commit. A commit failure is usually
# transient (a rebalance, a briefly unreachable broker), so a few
# backed-off attempts are worth making -- but not indefinitely, since
# an unbounded retry would hang the consumer instead of surfacing the
# problem.
COMMIT_RETRY_ATTEMPTS = 3
COMMIT_RETRY_BASE_SECONDS = 0.2


class BoundedSet:
    """Set-like membership tracking bounded to `max_size` entries, FIFO
    eviction (oldest insertion first) once full -- not LRU-on-read, so a
    membership check never refreshes an entry's position.
    """

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._data: OrderedDict[str, None] = OrderedDict()

    def add(self, item: str) -> None:
        if item in self._data:
            return
        if len(self._data) >= self._max_size:
            self._data.popitem(last=False)
        self._data[item] = None

    def __contains__(self, item: str) -> bool:
        return item in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BoundedSet):
            return set(self._data) == set(other._data)
        if isinstance(other, (set, frozenset)):
            return set(self._data) == other
        return NotImplemented


class BoundedUserStates:
    """A dict-like `user_id -> UserState` cache bounded to `max_size`
    entries, LRU eviction (oldest-accessed, not oldest-inserted, since a
    read here means "this user is still active" as much as a write does).

    Only the subset of dict's interface the two consumers and their
    tests actually use: indexing, `in`, `len`, and `setdefault`.
    """

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._data: OrderedDict[str, UserState] = OrderedDict()

    def __contains__(self, user_id: str) -> bool:
        return user_id in self._data

    def __getitem__(self, user_id: str) -> "UserState":
        state = self._data[user_id]
        self._data.move_to_end(user_id)
        return state

    def __setitem__(self, user_id: str, state: "UserState") -> None:
        self._data[user_id] = state
        self._data.move_to_end(user_id)
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def setdefault(self, user_id: str, default: "UserState") -> "UserState":
        if user_id in self._data:
            return self[user_id]
        self[user_id] = default
        return default


@dataclass
class UserState:
    """Recent, in-process state for one user -- not a durable store; a
    low-latency store (Redis) is the online feature store's separate concern. Bounded to
    the most recent `MAX_RECENT_ITEMS` clicks, the same fixed-window idea
    already used for offline click history (docs/experiments/retrieval-model.md), now
    built from live events instead of a pre-collected history string.
    """

    recent_clicked_items: deque = field(default_factory=lambda: deque(maxlen=MAX_RECENT_ITEMS))
    impressions_seen: int = 0
    clicks_seen: int = 0
    last_event_time: str | None = None


@dataclass
class MonitoringCounters:
    events_by_type: dict = field(default_factory=dict)
    malformed_rejected: int = 0
    duplicates_skipped: int = 0
    distinct_users: BoundedSet = field(default_factory=lambda: BoundedSet(MAX_DISTINCT_TRACKED))
    distinct_items: BoundedSet = field(default_factory=lambda: BoundedSet(MAX_DISTINCT_TRACKED))
    total_processed: int = 0


class StreamConsumer:
    """Turns raw Kafka message bytes into recent user state and
    monitoring counters: validates the payload, drops anything malformed
    or already-seen, then updates state for what's left. A malformed
    message is counted and discarded, never raised -- one bad message
    must not be able to stop the stream.

    A finite verification utility, not a production-capable consumer:
    `user_states` is this class's only copy of per-user state (no
    durable backing), so bounding it caps worst-case memory but does not
    prevent a long-running process from silently losing old users'
    history to eviction. `SyncingStreamConsumer` (`live_sync.py`) is the
    production-shaped subclass -- it treats Redis as authoritative and
    `user_states` there is a disposable read-through cache.
    """

    def __init__(
        self,
        max_seen_event_ids: int = MAX_SEEN_EVENT_IDS,
        max_distinct_tracked: int = MAX_DISTINCT_TRACKED,
        max_tracked_users: int = MAX_TRACKED_USERS,
    ) -> None:
        self.user_states = BoundedUserStates(max_tracked_users)
        self.counters = MonitoringCounters(
            distinct_users=BoundedSet(max_distinct_tracked),
            distinct_items=BoundedSet(max_distinct_tracked),
        )
        self._seen_event_ids = BoundedSet(max_seen_event_ids)

    def parse(self, raw) -> InteractionEvent | None:
        try:
            event = InteractionEvent.from_json(raw)
        except (ValueError, KeyError, TypeError):
            self.counters.malformed_rejected += 1
            return None
        if event.schema_version != SCHEMA_VERSION:
            self.counters.malformed_rejected += 1
            return None
        return event

    def process(self, raw) -> bool:
        """Returns True if `raw` was newly processed, False if it was
        rejected as malformed or skipped as a duplicate.
        """
        event = self.parse(raw)
        if event is None:
            return False
        if event.event_id in self._seen_event_ids:
            self.counters.duplicates_skipped += 1
            return False
        self._seen_event_ids.add(event.event_id)

        state = self._get_or_create_state(event.user_id)
        state.last_event_time = event.timestamp
        if event.event_type is EventType.IMPRESSION:
            state.impressions_seen += 1
        elif event.event_type is EventType.CLICK:
            state.clicks_seen += 1
            state.recent_clicked_items.append(event.item_id)
        if not self._on_state_updated(event.user_id, state, event.event_id):
            # A durable store rejected this as already applied (a
            # redelivery after a restart, which the in-process set above
            # cannot see). It has restored the correct state itself; the
            # event must not be counted a second time.
            self.counters.duplicates_skipped += 1
            return False

        self.counters.events_by_type[event.event_type.value] = (
            self.counters.events_by_type.get(event.event_type.value, 0) + 1
        )
        self.counters.distinct_users.add(event.user_id)
        self.counters.distinct_items.add(event.item_id)
        self.counters.total_processed += 1
        return True

    def _get_or_create_state(self, user_id: str) -> UserState:
        """Returns this user's current in-process state, creating a
        fresh one only if this process has never touched the user
        before. Overridable so a subclass backed by a durable store
        (SyncingStreamConsumer) can restore real prior state instead of
        starting empty after every restart -- an in-process-only default
        here silently overwrote a durable record with a blank one on
        the very first event after a restart (docs/operations/recovery-testing.md).
        """
        return self.user_states.setdefault(user_id, UserState())

    def _on_state_updated(self, user_id: str, state: UserState, event_id: str) -> bool:
        """Hook called every time an event updates a user's state, with
        the user id, their state exactly as it stands right after that
        update, and the id of the event that caused it. A plain
        StreamConsumer's only job is in-process state, so this always
        reports the update as newly applied.

        Returning False means a durable store recognized this event as
        already applied and has restored the correct state itself, so
        the caller must treat it as a duplicate rather than counting it
        again. `event_id` is passed so such a store can make the
        already-applied check and the state write one atomic operation;
        the in-process dedup set above cannot help there, since it
        starts empty after every restart.
        """
        return True


def run_consumer(
    stream_consumer: StreamConsumer,
    group_id: str,
    topic: str = TOPIC,
    bootstrap_servers: str = DEFAULT_BOOTSTRAP_SERVERS,
    max_messages: int | None = None,
    idle_timeout: float = 5.0,
) -> dict:
    """Polls `topic` and feeds every message through `stream_consumer`,
    committing the offset only after it's been processed -- so a crash
    between poll and commit leaves the offset unmoved and that message
    gets redelivered on restart, not silently lost (verified directly in
    the recovery testing that follows this step).

    That redelivery guarantee holds only while offsets are actually
    committed in order. A commit failure is therefore retried with
    bounded backoff, and consumption stops if the retries are exhausted:
    Kafka offsets are cumulative, so continuing would let the next
    successful commit also commit the failed message, and it would never
    be redelivered. The returned `stopped_on_commit_failure` reports
    whether the run ended that way rather than by reaching the end of
    the stream. Stops once no message
    arrives within `idle_timeout` seconds -- a real consumer polls
    forever, but a bounded run is what a finite verification pass needs.

    A real gotcha, found by testing against a live broker rather than
    assumed away: the *first* poll() on a fresh consumer group can return
    None simply because group/partition assignment hasn't finished yet,
    not because the topic is empty. Treating that first None as "done"
    would silently skip every message. So a None is only treated as
    genuine end-of-stream once at least one real message has already been
    received; before that, a bounded number of empty polls are tolerated
    as normal rebalance warm-up.
    """
    consumer = build_consumer(group_id, bootstrap_servers)
    consumer.subscribe([topic])
    polled = 0
    processed = 0
    commit_failures = 0
    stopped_on_commit_failure = False
    received_any = False
    empty_polls_before_first_message = 0
    try:
        while max_messages is None or polled < max_messages:
            msg = consumer.poll(idle_timeout)
            if msg is None:
                if received_any:
                    break
                empty_polls_before_first_message += 1
                if empty_polls_before_first_message > 5:
                    break  # topic genuinely appears empty, not just still rebalancing
                continue
            received_any = True
            if msg.error():
                continue
            polled += 1
            if stream_consumer.process(msg.value()):
                processed += 1
            # `asynchronous=False` blocks and raises on failure; the
            # default fire-and-forget made a real commit failure
            # invisible.
            #
            # Retried with bounded backoff, and consumption stops if the
            # retries are exhausted. Continuing past a failed commit is
            # not safe: Kafka offsets are cumulative, so committing a
            # later message also commits this one. The earlier claim that
            # a failed commit simply means redelivery was therefore wrong
            # -- the very next successful commit would silently bury it,
            # and the message would never be redelivered at all.
            committed = False
            for attempt in range(COMMIT_RETRY_ATTEMPTS):
                try:
                    consumer.commit(msg, asynchronous=False)
                    committed = True
                    break
                except KafkaException:
                    commit_failures += 1
                    COMMIT_FAILURES.inc()
                    if attempt < COMMIT_RETRY_ATTEMPTS - 1:
                        time.sleep(COMMIT_RETRY_BASE_SECONDS * (2**attempt))

            if not committed:
                # Stopping is the conservative choice: this message has
                # been applied but its offset is unconfirmed, so a
                # restart will redeliver it -- which the state store
                # handles idempotently. Carrying on would instead risk
                # burying it under a later commit and losing it outright.
                stopped_on_commit_failure = True
                break
    finally:
        consumer.close()
    return {
        "messages_polled": polled,
        "messages_processed": processed,
        "commit_failures": commit_failures,
        "stopped_on_commit_failure": stopped_on_commit_failure,
    }
