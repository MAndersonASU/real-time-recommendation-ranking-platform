from collections import OrderedDict, deque
from dataclasses import dataclass, field

from confluent_kafka import KafkaException

from recommender.streaming.kafka_client import DEFAULT_BOOTSTRAP_SERVERS, build_consumer
from recommender.streaming.replay_producer import TOPIC
from recommender.streaming.schema import SCHEMA_VERSION, EventType, InteractionEvent

MAX_RECENT_ITEMS = 20

# A real bug, found by audit: `_seen_event_ids` and the monitoring
# counters' `distinct_users`/`distinct_items` were plain, unbounded
# `set`s -- a long-running consumer process grows them forever, one
# entry per never-before-seen event id, user, or item, for as long as
# the process runs. Bounded here to a fixed capacity instead, evicting
# the oldest-inserted entry once full. A disclosed, intentional
# tradeoff, not a full fix for the underlying problem: `distinct_users`/
# `distinct_items` now mean "distinct among the most recently tracked
# `MAX_DISTINCT_TRACKED` entries," not "distinct across this process's
# entire lifetime" -- and duplicate detection only catches a redelivery
# that arrives within the same window. A durable, cross-restart dedup
# store is a materially larger change (the same tradeoff already named
# for these counters resetting across restarts) and out of scope here;
# this only fixes the unbounded in-process memory growth.
MAX_SEEN_EVENT_IDS = 100_000
MAX_DISTINCT_TRACKED = 100_000


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


@dataclass
class UserState:
    """Recent, in-process state for one user -- not a durable store; a
    low-latency store (Redis) is Phase 7's separate concern. Bounded to
    the most recent `MAX_RECENT_ITEMS` clicks, the same fixed-window idea
    already used for offline click history (docs/retrieval-model.md), now
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
    """

    def __init__(
        self,
        max_seen_event_ids: int = MAX_SEEN_EVENT_IDS,
        max_distinct_tracked: int = MAX_DISTINCT_TRACKED,
    ) -> None:
        self.user_states: dict[str, UserState] = {}
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
        self._on_state_updated(event.user_id, state)

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
        the very first event after a restart (docs/recovery-testing.md).
        """
        return self.user_states.setdefault(user_id, UserState())

    def _on_state_updated(self, user_id: str, state: UserState) -> None:
        """Hook called every time an event updates a user's state, with
        the user id and their state exactly as it stands right after that
        update. No-op here -- a plain StreamConsumer's only job is
        in-process state. A subclass that also needs to push each update
        through to an external low-latency store (the Redis-backed state
        store, `docs/state-store.md`) can
        override this without touching the parsing, dedup, or counting
        logic above it at all.
        """


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
    the recovery testing that follows this step). Stops once no message
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
            # `asynchronous=False` makes this call block and actually
            # raise on failure -- the previous default (`asynchronous=True`)
            # fires and forgets, so a real commit failure (the broker
            # briefly unreachable, a rebalance in progress) was silently
            # invisible, contradicting this function's own documented
            # redelivery guarantee. Counted, not re-raised: one failed
            # commit must not be able to kill the whole consumer loop --
            # the message will simply be redelivered on the next poll or
            # after a restart, the same safety net a real crash already
            # relies on.
            try:
                consumer.commit(msg, asynchronous=False)
            except KafkaException:
                commit_failures += 1
    finally:
        consumer.close()
    return {
        "messages_polled": polled,
        "messages_processed": processed,
        "commit_failures": commit_failures,
    }
