"""The atomic claim-and-apply script, exercised against a real Redis.

Idempotency and lost-update protection are the two properties the
streaming path depends on, and both live entirely inside a Lua script
executed by Redis. Every test of them until now ran against
`InMemoryRedis`, a Python reimplementation of the same contract written
by the same hand as the script.

That is a real gap, not a pedantic one: a Python stand-in cannot
reproduce `EVAL`'s actual atomicity, Redis's own type coercion, or the
fact that a Lua error aborts the script mid-way. A defect in the script
itself -- wrong return type, a nil where a number was expected, a branch
that never fires -- reproduces perfectly in the stand-in and fails only
in production.

Run against a live Redis. Raises rather than skipping if none is
reachable, because a check that quietly passes when its dependency is
absent is worse than no check:

    python -m recommender.features.verify_lua_idempotency
"""

import json

from recommender.features.state_store import (
    PROCESSED_KEY_PREFIX,
    build_client,
    claim_and_apply_event,
    load_recent_features,
)
from recommender.paths import mind_small_path

REPORT_PATH = mind_small_path("redis_lua_idempotency_report.json")
USER = "lua-idempotency-check-user"


def _reset(client) -> None:
    """Clears only this check's own keys, never a FLUSHDB.

    The same Redis may hold real recent-feature state; a check is not
    entitled to destroy it.
    """
    from recommender.features.state_store import KEY_PREFIX

    client.delete(f"{KEY_PREFIX}{USER}")
    for event_id in ("evt-a", "evt-b", "evt-c"):
        client.delete(f"{PROCESSED_KEY_PREFIX}{event_id}")


def verify_lua_idempotency(redis_url: str = "redis://localhost:6379/0") -> dict:
    client = build_client(redis_url)
    client.ping()
    _reset(client)

    checks: dict[str, str] = {}

    # 1. A first event applies and reports that it applied.
    status, state = claim_and_apply_event(
        client, "evt-a", USER, "click", "n1", "2019-11-14T08:00:00", 20
    )
    if status != 1 or state.clicks_seen != 1 or state.recent_clicked_items != ["n1"]:
        raise RuntimeError(f"first event did not apply cleanly: status={status} state={state}")
    checks["first_event_applies"] = "ok"

    # 2. A second, different event applies on top of it.
    status, state = claim_and_apply_event(
        client, "evt-b", USER, "click", "n2", "2019-11-14T09:00:00", 20
    )
    if status != 1 or state.clicks_seen != 2 or state.recent_clicked_items != ["n1", "n2"]:
        raise RuntimeError(f"second event did not accumulate: status={status} state={state}")
    checks["second_event_accumulates"] = "ok"

    # 3. Redelivery of the first event is refused and returns *current*
    #    state -- not the snapshot from when it was first applied. The
    #    rollback bug this replaced returned the old snapshot and
    #    silently discarded event B.
    status, state = claim_and_apply_event(
        client, "evt-a", USER, "click", "n1", "2019-11-14T08:00:00", 20
    )
    if status != 0:
        raise RuntimeError("redelivered event was not recognised as a duplicate")
    if state.clicks_seen != 2 or state.recent_clicked_items != ["n1", "n2"]:
        raise RuntimeError(f"duplicate rolled state backwards: {state}")
    checks["late_duplicate_does_not_roll_back"] = "ok"

    # 4. The durable record agrees with what the call reported.
    stored = load_recent_features(client, USER)
    if stored.clicks_seen != 2 or stored.recent_clicked_items != ["n1", "n2"]:
        raise RuntimeError(f"stored state disagrees with the returned state: {stored}")
    checks["returned_state_matches_store"] = "ok"

    # 5. An impression is counted as an impression, not as a click. The
    #    retry path once inferred event type from whether the state
    #    carried clicked items, so an impression for a user with click
    #    history was re-applied as a click.
    status, state = claim_and_apply_event(
        client, "evt-c", USER, "impression", "n9", "2019-11-14T10:00:00", 20
    )
    if state.clicks_seen != 2 or state.impressions_seen != 1 or "n9" in state.recent_clicked_items:
        raise RuntimeError(f"impression was not applied as an impression: {state}")
    checks["impression_is_not_counted_as_a_click"] = "ok"

    # 6. History is bounded by max_history, enforced inside the script
    #    rather than by the caller.
    _reset(client)
    for index in range(10):
        claim_and_apply_event(
            client, f"evt-bound-{index}", USER, "click", f"n{index}",
            "2019-11-14T08:00:00", 3,
        )
    bounded = load_recent_features(client, USER)
    if len(bounded.recent_clicked_items) != 3 or bounded.recent_clicked_items != ["n7", "n8", "n9"]:
        raise RuntimeError(f"max_history not enforced by the script: {bounded}")
    if bounded.clicks_seen != 10:
        raise RuntimeError(f"click count should not be truncated with history: {bounded}")
    checks["history_is_bounded_but_counts_are_not"] = "ok"

    for index in range(10):
        client.delete(f"{PROCESSED_KEY_PREFIX}evt-bound-{index}")
    _reset(client)

    return {
        "redis_url": redis_url,
        "backend": "real Redis via EVAL, not the in-process stand-in",
        "checks": checks,
        "all_passed": True,
    }


def main() -> None:
    report = verify_lua_idempotency()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
