"""Many writers, one user, real Redis, at the same instant.

`verify_lua_idempotency` exercises the claim-and-apply script correctly
but sequentially, so it cannot observe the failure this module targets:
two consumers mutating the same user's state simultaneously. That case
was covered only by `InMemoryRedis`, which runs every call on one thread
and therefore cannot interleave anything -- it will report success no
matter how badly the script races.

The property under test is that the script is the *only* place state is
derived. An earlier implementation read state into Python, computed a
new value and wrote it back; two consumers that both read before either
wrote each produced a complete state from a stale basis, and the second
overwrote the first. Applying the event delta inside `EVAL` removes the
local basis entirely, and Redis executes each script to completion
before starting the next, so concurrent writers serialise rather than
collide.

Three things are asserted, each against genuinely parallel clients:

1. Every unique event applies exactly once -- no lost updates.
2. Concurrent redeliveries of already-applied events change nothing.
3. Mixed new-and-duplicate traffic lands only the new events.

Each thread holds its own `redis.Redis`, because a shared client would
serialise on its own connection pool and quietly test nothing. Threads
are released together by a `threading.Barrier`, so they contend rather
than merely running one after another.

Run against a live Redis:

    python -m recommender.features.verify_lua_concurrency
"""

import json
import threading
from collections import Counter

from recommender.features.state_store import (
    KEY_PREFIX,
    PROCESSED_KEY_PREFIX,
    build_client,
    claim_and_apply_event,
    load_recent_features,
)
from recommender.paths import mind_small_path

REPORT_PATH = mind_small_path("redis_lua_concurrency_report.json")
USER = "lua-concurrency-check-user"

# Enough writers to interleave on any machine, and enough events that a
# single lost update shows up as a wrong count rather than hiding inside
# a rounding tolerance -- there is no tolerance here, the counts are
# exact.
WRITERS = 8
EVENTS_PER_WRITER = 25
TOTAL_EVENTS = WRITERS * EVENTS_PER_WRITER

# Longer than the item history so the click count and the history bound
# are exercised independently: history truncates, counts must not.
MAX_HISTORY = 20

# Repeated because a race that fails one run in ten is still a race. A
# single green pass proves very little about concurrency.
ROUNDS = 5


def _reset(client, event_ids) -> None:
    """Removes only this check's own keys. Never a FLUSHDB -- the same
    Redis may hold real recent-feature state.
    """
    client.delete(f"{KEY_PREFIX}{USER}")
    for event_id in event_ids:
        client.delete(f"{PROCESSED_KEY_PREFIX}{event_id}")


def _submit_concurrently(redis_url: str, assignments: list[list[tuple[str, str]]]) -> Counter:
    """Runs one batch per writer, all released at the same moment.

    Returns the tally of applied (1) and duplicate (0) statuses the
    script itself reported, which is what lets a caller distinguish
    "applied twice" from "applied once and correctly refused".
    """
    barrier = threading.Barrier(len(assignments))
    statuses: Counter = Counter()
    lock = threading.Lock()
    failures: list[BaseException] = []

    def worker(batch: list[tuple[str, str]]) -> None:
        # One client per thread. Sharing a client would serialise these
        # calls inside the connection pool, and the test would pass
        # without ever having run anything concurrently.
        client = build_client(redis_url)
        local: Counter = Counter()
        try:
            barrier.wait(timeout=30)
            for event_id, item_id in batch:
                status, _state = claim_and_apply_event(
                    client, event_id, USER, "click", item_id,
                    "2019-11-14T08:00:00", MAX_HISTORY,
                )
                local[status] += 1
        except BaseException as error:  # noqa: BLE001 - reported, not swallowed
            with lock:
                failures.append(error)
        finally:
            with lock:
                statuses.update(local)

    threads = [threading.Thread(target=worker, args=(batch,)) for batch in assignments]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    if failures:
        raise RuntimeError(f"a concurrent writer failed: {failures[0]!r}") from failures[0]
    return statuses


def _batches(event_ids: list[str]) -> list[list[tuple[str, str]]]:
    """Interleaves the assignment so adjacent event ids land on
    different writers, maximising contention on the same user key.
    """
    return [
        [(event_ids[i], f"n{i}") for i in range(writer, len(event_ids), WRITERS)]
        for writer in range(WRITERS)
    ]


def verify_lua_concurrency(redis_url: str = "redis://localhost:6379/0", rounds: int = ROUNDS) -> dict:
    client = build_client(redis_url)
    client.ping()

    checks: dict[str, str] = {}
    event_ids = [f"conc-evt-{i}" for i in range(TOTAL_EVENTS)]

    for round_index in range(rounds):
        _reset(client, event_ids)

        # 1. Every unique event applies exactly once.
        statuses = _submit_concurrently(redis_url, _batches(event_ids))
        if statuses[1] != TOTAL_EVENTS:
            raise RuntimeError(
                f"round {round_index}: {statuses[1]} events reported applied, expected "
                f"{TOTAL_EVENTS}; {statuses[0]} were refused as duplicates. Unique "
                f"events must never be refused."
            )

        state = load_recent_features(client, USER)
        if state is None or state.clicks_seen != TOTAL_EVENTS:
            raise RuntimeError(
                f"round {round_index}: clicks_seen is "
                f"{None if state is None else state.clicks_seen}, expected "
                f"{TOTAL_EVENTS}. A lower count is a lost update -- two writers "
                f"derived state from the same stale basis."
            )
        if len(state.recent_clicked_items) != MAX_HISTORY:
            raise RuntimeError(
                f"round {round_index}: history holds "
                f"{len(state.recent_clicked_items)} items, expected the "
                f"{MAX_HISTORY} bound"
            )
        if len(set(state.recent_clicked_items)) != len(state.recent_clicked_items):
            raise RuntimeError(
                f"round {round_index}: history contains duplicates "
                f"{state.recent_clicked_items}, so an event was applied more than once"
            )

        # 2. Concurrent redelivery of everything changes nothing.
        redelivery = _submit_concurrently(redis_url, _batches(event_ids))
        if redelivery[0] != TOTAL_EVENTS:
            raise RuntimeError(
                f"round {round_index}: {redelivery[1]} redelivered events were applied "
                f"again; every one should have been refused"
            )

        after = load_recent_features(client, USER)
        if after.clicks_seen != TOTAL_EVENTS:
            raise RuntimeError(
                f"round {round_index}: redelivery changed clicks_seen from "
                f"{TOTAL_EVENTS} to {after.clicks_seen}"
            )
        if after.recent_clicked_items != state.recent_clicked_items:
            raise RuntimeError(
                f"round {round_index}: redelivery changed the history from "
                f"{state.recent_clicked_items} to {after.recent_clicked_items}"
            )

        # 3. Mixed traffic: half already applied, half genuinely new,
        #    submitted together. Only the new ones may land.
        new_ids = [f"conc-evt-new-{round_index}-{i}" for i in range(TOTAL_EVENTS // 2)]
        mixed = event_ids[: TOTAL_EVENTS // 2] + new_ids
        mixed_statuses = _submit_concurrently(
            redis_url,
            [
                [(mixed[i], f"m{i}") for i in range(writer, len(mixed), WRITERS)]
                for writer in range(WRITERS)
            ],
        )
        if mixed_statuses[1] != len(new_ids):
            raise RuntimeError(
                f"round {round_index}: mixed batch applied {mixed_statuses[1]} events, "
                f"expected exactly the {len(new_ids)} new ones"
            )

        final = load_recent_features(client, USER)
        if final.clicks_seen != TOTAL_EVENTS + len(new_ids):
            raise RuntimeError(
                f"round {round_index}: final clicks_seen is {final.clicks_seen}, "
                f"expected {TOTAL_EVENTS + len(new_ids)}"
            )
        _reset(client, event_ids + new_ids)

    checks["unique_events_apply_exactly_once"] = "ok"
    checks["concurrent_redelivery_changes_nothing"] = "ok"
    checks["mixed_batch_applies_only_new_events"] = "ok"
    checks["history_stays_bounded_and_duplicate_free"] = "ok"

    return {
        "redis_url": redis_url,
        "backend": "real Redis via EVAL, independent client per thread",
        "writers": WRITERS,
        "events_per_round": TOTAL_EVENTS,
        "rounds": rounds,
        "synchronisation": "threading.Barrier releases every writer together",
        "checks": checks,
        "all_passed": True,
    }


def main() -> None:
    report = verify_lua_concurrency()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
