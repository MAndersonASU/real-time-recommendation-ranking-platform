import json
from pathlib import Path

import pandas as pd

from recommender.features.online_features import recent_features_from_user_state
from recommender.features.parity import compute_recent_features_offline
from recommender.streaming.consumer import StreamConsumer
from recommender.streaming.replay_producer import events_for_row, load_replay_events

REPORT_PATH = Path("data/processed/mind_small/parity_verification_report.json")


def verify_parity(min_distinct_times: int = 5) -> dict:
    """Picks one real user from the reserved replay split (docs/splits.md)
    who was shown impressions at several genuinely different times (not
    just many candidate rows within a single session -- explode_impressions
    gives every candidate in one impression the same timestamp, so row
    count alone can pick a user with only one real moment in time), and
    confirms an independent offline recomputation of their recent
    features agrees exactly with what the real streaming consumer
    produces from the same real events, at three different real
    historical cutoffs. This is the training-serving skew check this
    step exists for, run against real data rather than a synthetic
    stand-in.
    """
    exploded = load_replay_events()
    distinct_times = exploded.groupby("user_id")["time"].nunique()
    candidates = distinct_times[distinct_times >= min_distinct_times]
    if candidates.empty:
        raise RuntimeError("no user in the replay split has enough distinct impression times")
    user_id = candidates.index[0]

    user_rows = exploded[exploded["user_id"] == user_id].sort_values(["time", "impression_id"])
    events = []
    for row in user_rows.itertuples():
        impression_event, outcome_event = events_for_row(row)
        events.extend([impression_event, outcome_event])

    unique_times = sorted(user_rows["time"].unique())
    checkpoint_times = sorted(
        {unique_times[0], unique_times[len(unique_times) // 2], unique_times[-1]}
    )
    results = []
    for checkpoint_time in checkpoint_times:
        cutoff = pd.Timestamp(checkpoint_time).isoformat()
        offline = compute_recent_features_offline(events, user_id, cutoff)

        consumer = StreamConsumer()
        relevant = sorted((e for e in events if e.timestamp <= cutoff), key=lambda e: e.timestamp)
        for event in relevant:
            consumer.process(event.to_json())
        online = recent_features_from_user_state(user_id, consumer.user_states[user_id])

        results.append(
            {
                "cutoff": cutoff,
                "matches": online == offline,
                "clicks_seen": offline.clicks_seen,
                "impressions_seen": offline.impressions_seen,
            }
        )

    return {
        "user_id": user_id,
        "total_impressions_for_user": len(user_rows),
        "checkpoints": results,
        "all_checkpoints_match": all(r["matches"] for r in results),
    }


def main() -> None:
    report = verify_parity()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
