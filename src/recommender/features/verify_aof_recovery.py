"""Does an acknowledged write actually survive an abrupt kill?

`docker-compose.yml` enables AOF with `appendfsync everysec` and the
documentation states a bounded durability guarantee: at most about one
second of acknowledged writes can be lost. That was configuration plus
prose, with nothing demonstrating it.

The distinction matters because the failure it guards against is not a
clean shutdown. `docker stop` sends SIGTERM and Redis flushes on the way
out, so a stop/start cycle proves nothing about durability -- it would
pass even with AOF disabled entirely. This uses `docker kill` (SIGKILL),
which is what a real crash looks like: no flush, no handler, nothing but
whatever already reached the append-only file.

Run with the compose Redis up:

    python -m recommender.features.verify_aof_recovery
"""

import json
import subprocess
import time

from recommender.features.state_store import (
    build_client,
    claim_and_apply_event,
    load_recent_features,
)
from recommender.paths import mind_small_path

REPORT_PATH = mind_small_path("redis_aof_recovery_report.json")
CONTAINER = "recommender-redis"
USER = "aof-recovery-check-user"

# The configured appendfsync policy is `everysec`, so a write is on disk
# within about a second of being acknowledged. Waiting comfortably past
# that before killing is what makes this a test of the *guarantee*
# rather than a race: writes younger than the fsync interval are
# expected to be lost, and that is the documented bound.
FSYNC_WAIT_SECONDS = 2.5


def _docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=60
    )
    return result.stdout.strip()


def _wait_until_healthy(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = _docker(
            "inspect", "--format", "{{.State.Health.Status}}", CONTAINER
        )
        if status == "healthy":
            return
        time.sleep(2)
    raise RuntimeError(f"{CONTAINER} did not become healthy within {timeout_seconds}s")


def verify_aof_recovery(redis_url: str = "redis://localhost:6379/0") -> dict:
    client = build_client(redis_url)
    client.ping()

    # Confirm the policy being tested is actually in force, rather than
    # assuming compose applied it. A passing recovery test against a
    # Redis with AOF off would be meaningless.
    appendonly = client.config_get("appendonly").get("appendonly")
    appendfsync = client.config_get("appendfsync").get("appendfsync")
    if appendonly != "yes":
        raise RuntimeError(f"AOF is not enabled (appendonly={appendonly!r}); nothing to verify")

    from recommender.features.state_store import KEY_PREFIX, PROCESSED_KEY_PREFIX

    client.delete(f"{KEY_PREFIX}{USER}")
    client.delete(f"{PROCESSED_KEY_PREFIX}aof-evt-1")
    client.delete(f"{PROCESSED_KEY_PREFIX}aof-evt-2")

    claim_and_apply_event(client, "aof-evt-1", USER, "click", "n1", "2019-11-14T08:00:00", 20)
    claim_and_apply_event(client, "aof-evt-2", USER, "click", "n2", "2019-11-14T09:00:00", 20)

    before = load_recent_features(client, USER)
    if before is None or before.clicks_seen != 2:
        raise RuntimeError(f"state was not written before the kill: {before}")

    time.sleep(FSYNC_WAIT_SECONDS)

    # SIGKILL, not SIGTERM. A graceful stop flushes on exit and would
    # pass even with AOF disabled.
    _docker("kill", CONTAINER)
    _docker("start", CONTAINER)
    _wait_until_healthy()

    recovered_client = build_client(redis_url)
    recovered_client.ping()
    after = load_recent_features(recovered_client, USER)

    if after is None:
        raise RuntimeError(
            "acknowledged writes did not survive an abrupt kill: the user's state is "
            "gone entirely after restart, so the documented durability bound does not hold"
        )
    if after.clicks_seen != before.clicks_seen or after.recent_clicked_items != before.recent_clicked_items:
        raise RuntimeError(
            f"state changed across the kill: before={before} after={after}"
        )

    # The idempotency claim must survive too. If the claim markers were
    # lost while the state survived, a redelivery after a crash would be
    # applied a second time on top of already-counted state.
    status, _ = claim_and_apply_event(
        recovered_client, "aof-evt-1", USER, "click", "n1", "2019-11-14T08:00:00", 20
    )
    if status != 0:
        raise RuntimeError(
            "the processed-event claim did not survive the kill, so a post-crash "
            "redelivery would be double-counted"
        )

    recovered_client.delete(f"{KEY_PREFIX}{USER}")
    for event_id in ("aof-evt-1", "aof-evt-2"):
        recovered_client.delete(f"{PROCESSED_KEY_PREFIX}{event_id}")

    return {
        "container": CONTAINER,
        "signal": "SIGKILL via docker kill (not a graceful stop)",
        "appendonly": appendonly,
        "appendfsync": appendfsync,
        "fsync_wait_seconds": FSYNC_WAIT_SECONDS,
        "clicks_before": before.clicks_seen,
        "clicks_after": after.clicks_seen,
        "state_survived": True,
        "idempotency_claim_survived": True,
        "bound": (
            "writes acknowledged more than one fsync interval before the kill survive. "
            "Writes newer than that may be lost, by design -- appendfsync everysec is "
            "not per-write durability."
        ),
    }


def main() -> None:
    report = verify_aof_recovery()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
