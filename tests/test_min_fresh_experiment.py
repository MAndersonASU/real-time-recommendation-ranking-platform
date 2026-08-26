"""The selection rule has to be right before it produces a number.

`docs/min-fresh-experiment-protocol.md` was frozen before the experiment
ran, which only means something if the code implements the frozen rule.
These tests pin the rule itself against synthetic outcomes, where the
correct answer is known in advance -- so a bug in the rule cannot be
mistaken for a finding about the recommender.
"""

import numpy as np
import pandas as pd
import pytest

from recommender.evaluation.min_fresh_experiment import (
    BASELINE_QUOTA,
    DEPLOYED_QUOTA,
    HIT_RATE_RETENTION_FLOOR,
    NDCG_RETENTION_FLOOR,
    QUOTAS,
    analyse,
)


def _outcomes(retention_by_quota, users=60, impressions_per_user=4):
    """Synthetic outcomes where each quota retains a known fraction of
    the baseline, with no noise -- so the bound is driven by the effect
    rather than by sampling.
    """
    records = []
    for user in range(users):
        for impression in range(impressions_per_user):
            for quota in QUOTAS:
                retention = retention_by_quota[quota]
                records.append(
                    {
                        "user_id": f"U{user}",
                        "impression_id": f"U{user}-{impression}",
                        "quota": quota,
                        "ndcg_at_k": 0.5 * retention,
                        "hit_rate_at_k": 1.0 * retention,
                        "mean_slate_relevance": 5.0 * retention,
                        "fresh_items": quota,
                        "meets_quota": 1,
                        "distinct_categories": 6,
                    }
                )
    return pd.DataFrame.from_records(records)


def test_the_largest_passing_quota_is_selected():
    """Everything retains fully, so every quota clears both bounds and
    the rule takes the largest.
    """
    result = analyse(_outcomes(dict.fromkeys(QUOTAS, 1.0)))

    assert result["selected_quota"] == max(q for q in QUOTAS if q != BASELINE_QUOTA)
    assert result["quotas_passing_both_bounds"] == [1, 2, 3, 5]


def test_a_quota_failing_the_primary_bound_is_excluded():
    """Quota 5 loses 5% of NDCG -- well under the 99% floor -- so the
    rule must drop it and take the largest that survives.
    """
    result = analyse(_outcomes({0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 5: 0.95}))

    assert 5 not in result["quotas_passing_both_bounds"]
    assert result["selected_quota"] == 3


def test_the_hit_rate_guardrail_can_exclude_a_quota_the_primary_accepts():
    """NDCG is intact but hit rate collapses. The guardrail exists for
    exactly this: a reordering that preserves graded gain while pushing
    the clicked item out of the slate entirely.
    """
    outcomes = _outcomes(dict.fromkeys(QUOTAS, 1.0))
    collapsed = outcomes["quota"] == 5
    outcomes.loc[collapsed, "hit_rate_at_k"] = 0.5

    result = analyse(outcomes)

    assert 5 not in result["quotas_passing_both_bounds"]
    assert result["selected_quota"] == 3


def test_no_passing_quota_reports_no_support_rather_than_a_default():
    """The case the protocol calls out explicitly. If nothing passes,
    the rule must say the evidence supports no quota -- not silently
    fall back to the deployed value.
    """
    result = analyse(_outcomes({0: 1.0, 1: 0.5, 2: 0.5, 3: 0.5, 5: 0.5}))

    assert result["quotas_passing_both_bounds"] == []
    assert result["selected_quota"] is None
    assert "explicit product override" in result["outcome_statement"]
    assert result["rule_selects_deployed_value"] is False


def test_the_baseline_quota_is_never_selected():
    """Quota 0 is the comparison point, not a candidate."""
    result = analyse(_outcomes(dict.fromkeys(QUOTAS, 1.0)))

    assert BASELINE_QUOTA not in result["quotas_passing_both_bounds"]


def test_the_bootstrap_clusters_by_user_not_impression():
    """Clustering must matter, or it is decoration.

    Here every user is internally consistent and users differ sharply.
    Resampling users therefore produces a genuinely wide interval;
    resampling impressions independently would average that structure
    away and report a falsely tight bound.
    """
    records = []
    for user in range(40):
        # Half the users lose nothing under quota 2; half lose heavily.
        retention = 1.0 if user % 2 == 0 else 0.4
        for impression in range(10):
            for quota in QUOTAS:
                value = retention if quota == 2 else 1.0
                records.append(
                    {
                        "user_id": f"U{user}",
                        "impression_id": f"U{user}-{impression}",
                        "quota": quota,
                        "ndcg_at_k": 0.5 * value,
                        "hit_rate_at_k": 1.0 * value,
                        "mean_slate_relevance": 5.0,
                        "fresh_items": quota,
                        "meets_quota": 1,
                        "distinct_categories": 6,
                    }
                )
    result = analyse(pd.DataFrame.from_records(records))

    bound = result["per_quota"]["2"]["ndcg_at_10"]["retention_lower_bound_95"]
    observed = result["per_quota"]["2"]["ndcg_at_10"]["observed_retention"]

    assert bound < observed, "a clustered bootstrap must produce a bound below the point estimate"
    assert bound < NDCG_RETENTION_FLOOR
    assert 2 not in result["quotas_passing_both_bounds"]


def test_retention_is_measured_against_quota_zero():
    result = analyse(_outcomes({0: 1.0, 1: 0.8, 2: 0.8, 3: 0.8, 5: 0.8}))

    assert result["per_quota"]["1"]["ndcg_at_10"]["observed_retention"] == pytest.approx(0.8)
    assert result["per_quota"]["0"]["ndcg_at_10"]["observed_retention"] == pytest.approx(1.0)


def test_diagnostics_are_reported_but_do_not_drive_selection():
    """Freshness rises monotonically with the quota, so a rule that read
    diagnostics would always pick the largest value -- the failure the
    diversity-cap rule already made once.
    """
    outcomes = _outcomes({0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 5: 0.5})
    outcomes.loc[outcomes["quota"] == 5, "fresh_items"] = 99

    result = analyse(outcomes)

    assert result["per_quota"]["5"]["diagnostics"]["mean_fresh_items_in_slate"] == 99
    assert 5 not in result["quotas_passing_both_bounds"], (
        "an excellent freshness diagnostic must not rescue a quota that fails the "
        "relevance bounds"
    )


def test_the_frozen_constants_match_the_committed_protocol():
    """Guards against the rule drifting from the document it transcribes."""
    assert NDCG_RETENTION_FLOOR == 0.99
    assert HIT_RATE_RETENTION_FLOOR == 0.95
    assert QUOTAS == (0, 1, 2, 3, 5)
    assert BASELINE_QUOTA == 0
    assert DEPLOYED_QUOTA == 2

    from pathlib import Path

    protocol = Path("docs/min-fresh-experiment-protocol.md")
    if not protocol.exists():
        pytest.skip("protocol document not present")
    text = protocol.read_text(encoding="utf-8")
    assert "99% retention" in text
    assert "hit-rate@10 retention ≥ 95%" in text
    assert "{0, 1, 2, 3, 5}" in text


def test_analysis_needs_only_the_stored_outcomes():
    """The bootstrap stage must run from the outcomes table alone -- no
    models, no Redis, no licensed reload. That is what lets the
    expensive scoring pass happen once.
    """
    outcomes = _outcomes(dict.fromkeys(QUOTAS, 1.0))
    round_tripped = pd.DataFrame(np.asarray(outcomes), columns=outcomes.columns)
    round_tripped = round_tripped.astype(outcomes.dtypes.to_dict())

    assert analyse(round_tripped)["selected_quota"] == 5
