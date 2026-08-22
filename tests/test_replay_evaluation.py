import pandas as pd

from recommender.tracking.replay_evaluation import evaluate_via_replay
from tests.test_pipeline import _build_context

REPLAY_BEHAVIORS = pd.DataFrame(
    {
        "impression_id": [10, 11],
        "user_id": ["u1", "u2"],
        "time": pd.to_datetime(["2019-11-15T08:00:00", "2019-11-15T09:00:00"]),
        "history": ["n1 n2", "n4"],
        # n1 was really clicked in impression 10; n6 was really clicked in
        # impression 11 -- both real catalog items from the test fixture.
        "impressions": ["n1-1 n3-0", "n5-0 n6-1"],
    }
)


def test_evaluate_via_replay_reports_the_real_sampled_and_clicked_counts():
    context = _build_context()

    report = evaluate_via_replay(context, num_impressions=2, k=3, replay=REPLAY_BEHAVIORS)

    assert report["impressions_sampled"] == 2
    assert report["impressions_with_a_real_click"] == 2
    assert report["k"] == 3
    assert report["is_a_replay_simulation_not_a_live_ab_test"] is True


def test_evaluate_via_replay_hit_rate_is_between_zero_and_one():
    context = _build_context()

    report = evaluate_via_replay(context, num_impressions=2, k=3, replay=REPLAY_BEHAVIORS)

    assert 0.0 <= report["hit_rate_at_k"] <= 1.0


def test_evaluate_via_replay_skips_impressions_with_no_real_click():
    context = _build_context()
    no_click_behaviors = pd.DataFrame(
        {
            "impression_id": [20],
            "user_id": ["u1"],
            "time": pd.to_datetime(["2019-11-15T08:00:00"]),
            "history": ["n1"],
            "impressions": ["n2-0 n3-0"],
        }
    )

    report = evaluate_via_replay(context, num_impressions=1, k=3, replay=no_click_behaviors)

    assert report["impressions_with_a_real_click"] == 0
    assert report["hit_rate_at_k"] == 0.0


def test_evaluate_via_replay_respects_the_num_impressions_sample_size():
    context = _build_context()

    report = evaluate_via_replay(context, num_impressions=1, k=3, replay=REPLAY_BEHAVIORS)

    assert report["impressions_sampled"] == 1


def test_evaluate_via_replay_records_the_recent_features_toggle_and_a_real_latency_sample():
    context = _build_context()

    with_recent = evaluate_via_replay(context, num_impressions=2, k=3, replay=REPLAY_BEHAVIORS)
    without_recent = evaluate_via_replay(
        context, num_impressions=2, k=3, replay=REPLAY_BEHAVIORS, use_recent_features=False
    )

    assert with_recent["use_recent_features"] is True
    assert without_recent["use_recent_features"] is False
    assert with_recent["mean_feature_lookup_ms"] is not None
    assert without_recent["mean_feature_lookup_ms"] is not None
