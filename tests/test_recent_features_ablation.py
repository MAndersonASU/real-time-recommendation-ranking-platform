from unittest.mock import patch

import pytest

from recommender.tracking.recent_features_ablation import run_recent_features_ablation


def _replay_result(digest: str, **overrides) -> dict:
    result = {
        "sampling": {"selected_ids_sha256": digest, "seed": 20260825},
        "impressions_evaluated": 500,
        "hit_rate_at_k": 0.05,
    }
    result.update(overrides)
    return result


def test_matching_sample_digests_produce_a_paired_report():
    with (
        patch("recommender.tracking.recent_features_ablation.build_serving_context"),
        patch(
            "recommender.tracking.recent_features_ablation.evaluate_via_replay",
            side_effect=[_replay_result("same-digest"), _replay_result("same-digest")],
        ),
    ):
        report = run_recent_features_ablation()

    assert report["sampling"]["selected_ids_sha256"] == "same-digest"
    assert "with_recent_features" in report
    assert "without_recent_features" in report


def test_mismatched_sample_digests_are_rejected_not_silently_published():
    """Regression test for a real bug, found by audit: this invariant
    used a bare `assert`, which `python -O` compiles out entirely --
    an unpaired comparison (the two arms scoring different impression
    samples) would then continue and publish without ever being caught.
    Fails on the pre-fix code under `python -O` (nothing raises, the
    mismatched report publishes) and passes here regardless of how the
    interpreter is invoked, since an explicit `ValueError` is never
    compiled out.
    """
    with (
        patch("recommender.tracking.recent_features_ablation.build_serving_context"),
        patch(
            "recommender.tracking.recent_features_ablation.evaluate_via_replay",
            side_effect=[_replay_result("digest-a"), _replay_result("digest-b")],
        ),
        pytest.raises(ValueError, match="different impressions"),
    ):
        run_recent_features_ablation()
