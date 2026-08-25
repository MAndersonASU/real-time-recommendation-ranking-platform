"""The tuning report's publishing step must not be able to throw away a
finished run.

`verify_tuning_decisions` measures for roughly twenty minutes across
millions of feature rows, then publishes. An earlier version reached for
`report["diversity_cap"]["sampling"]`, one level above where the
description actually sits, and the `KeyError` surfaced only after all of
that work had completed and been discarded. These tests exercise the
accessor against the real nested shape, which costs milliseconds.
"""

import pytest

from recommender.evaluation.sampling import DEFAULT_SAMPLE_SEED
from recommender.evaluation.verify_tuning_decisions import collect_sampling


def _sampling(n):
    return {
        "method": "seeded uniform random without replacement",
        "seed": DEFAULT_SAMPLE_SEED,
        "eligible_impressions": 25140,
        "selected_impressions": n,
        "selected_ids_sha256": "abc123",
    }


@pytest.fixture
def report():
    """The real nesting: each comparison's sampling sits inside its own
    comparison sub-object, not beside the section it belongs to.
    """
    return {
        "popularity_exclusion": {"decision_confirmed": True},
        "diversity_cap": {
            "decision_confirmed": True,
            "cap_value_comparison": {
                "sample_impressions": 1500,
                "sampling": _sampling(1500),
                "currently_configured_cap": 3,
            },
        },
        "freshness_threshold": {
            "min_fresh_value_comparison": {
                "sampling": _sampling(1500),
                "currently_configured_min_fresh_in_slate": 2,
            },
        },
        "retrieval_depth": {"impressions_measured": 400},
    }


def test_every_comparisons_sampling_is_found(report):
    collected = collect_sampling(report)

    assert set(collected["by_comparison"]) == {
        "diversity_cap.cap_value_comparison",
        "freshness_threshold.min_fresh_value_comparison",
    }
    assert collected["seed"] == DEFAULT_SAMPLE_SEED


def test_a_restructured_report_does_not_crash_publishing(report):
    """The specific failure being prevented. Moving a comparison changes
    which paths are reported; it must not raise, because raising here
    discards a completed measurement run.
    """
    report["diversity_cap"]["renamed_comparison"] = report["diversity_cap"].pop(
        "cap_value_comparison"
    )

    collected = collect_sampling(report)

    assert "diversity_cap.renamed_comparison" in collected["by_comparison"]


def test_a_report_with_no_sampling_still_publishes(report):
    """An all-population run is a real case and must not fail. It
    reports an empty set of comparisons rather than a missing field.
    """
    collected = collect_sampling({"popularity_exclusion": {"decision_confirmed": True}})

    assert collected["by_comparison"] == {}
    assert collected["method"]


def test_the_collected_description_satisfies_the_report_contract(report):
    """`validate_report` rejects an empty sampling block, so the
    collector's output has to be non-empty even when nothing was
    sampled.
    """
    from recommender.evaluation.reports import validate_report

    built = {
        "report_name": "tuning-decisions",
        "schema_version": 2,
        "provenance": {
            "source_commit": "0" * 40,
            "working_tree_clean": True,
            "generated_at": "2026-08-25T00:00:00+00:00",
            "evaluation_module": "recommender.evaluation.verify_tuning_decisions",
        },
        "dataset": {},
        "artifacts": {},
        "configuration": {},
        "sampling": collect_sampling(report),
        "denominators": {"sampled_impressions": 1500},
        "metric_definitions": {"decision_confirmed": "whether the original call held up"},
        "results": {"decision_confirmed": True},
        "limitations": [],
    }

    validate_report(built)  # must not raise
