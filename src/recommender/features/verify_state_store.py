import json
import time
from pathlib import Path

from recommender.features.online_features import RecentUserFeatures
from recommender.features.state_store import (
    build_client,
    load_recent_features,
    save_recent_features,
)

REPORT_PATH = Path("data/processed/mind_small/redis_connectivity_report.json")
CHECK_USER_ID = "connectivity-check-user"
N_LOOKUPS = 200


def verify_state_store(redis_url: str = "redis://localhost:6379/0") -> dict:
    """Writes one real record to a real Redis, reads it back, and confirms
    every field round-trips exactly -- not a mock, if no Redis is
    reachable this raises rather than reporting a false pass. Also
    measures real read latency over N_LOOKUPS gets, since "low-latency"
    is a claim this step needs to actually back with a number, not just
    assert.
    """
    client = build_client(redis_url)
    client.ping()

    written = RecentUserFeatures(
        user_id=CHECK_USER_ID,
        recent_clicked_items=["n1", "n2", "n3"],
        impressions_seen=5,
        clicks_seen=3,
        last_event_time="2019-11-15T08:00:00",
    )
    save_recent_features(client, written)
    read_back = load_recent_features(client, CHECK_USER_ID)
    if read_back != written:
        raise RuntimeError("value read back from Redis did not match what was written")

    latencies_ms = []
    for _ in range(N_LOOKUPS):
        start = time.perf_counter()
        load_recent_features(client, CHECK_USER_ID)
        latencies_ms.append((time.perf_counter() - start) * 1000)
    latencies_ms.sort()

    missing = load_recent_features(client, "a-user-that-has-never-sent-an-event")
    if missing is not None:
        raise RuntimeError("an unknown user should read back as None, not a stale record")

    return {
        "redis_url": redis_url,
        "round_trip_matches": True,
        "unknown_user_returns_none": True,
        "lookup_count": N_LOOKUPS,
        "p50_latency_ms": round(latencies_ms[N_LOOKUPS // 2], 3),
        "p99_latency_ms": round(latencies_ms[int(N_LOOKUPS * 0.99)], 3),
    }


def main() -> None:
    report = verify_state_store()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
