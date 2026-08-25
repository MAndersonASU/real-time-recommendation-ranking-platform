import json

import pytest

from recommender.evaluation.reports import (
    REPORT_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    build_report,
    validate_report,
    write_report,
)


def _report(**overrides):
    report = build_report(
        report_name="example-evaluation",
        dataset={"name": "MIND small", "split": "validation", "edition": "2019-11"},
        configuration={"k": 10, "seed": 42},
        denominators={"impressions_evaluated": 2000, "users": 1500},
        metric_definitions={"hit_rate_at_k": "share of impressions whose clicked item is in the top K"},
        results={"hit_rate_at_k": 0.0145},
        limitations=["retrieval remains the binding constraint"],
    )
    report.update(overrides)
    return report


def test_a_built_report_carries_full_provenance():
    report = _report()

    for field in REQUIRED_FIELDS:
        assert field in report, field

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["generated_at"].endswith("+00:00")
    # Ties the numbers to the exact artifacts that produced them, so a
    # later artifact change shows up as a changed hash rather than an
    # unexplained metric shift.
    assert "retrieval_model_sha256_prefix" in report["artifacts"]
    assert "serving_code_commit" in report["artifacts"]


def test_validate_accepts_a_well_formed_report():
    validate_report(_report())  # must not raise


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_validate_rejects_a_report_missing_any_required_field(field):
    report = _report()
    del report[field]

    with pytest.raises(ValueError, match="missing required fields"):
        validate_report(report)


def test_validate_rejects_a_stale_schema_version():
    """A committed report from an older contract must not be read as if
    it followed the current one.
    """
    with pytest.raises(ValueError, match="schema version"):
        validate_report(_report(schema_version=REPORT_SCHEMA_VERSION + 1))


def test_validate_rejects_an_empty_result_set():
    with pytest.raises(ValueError, match="no results"):
        validate_report(_report(results={}))


def test_validate_requires_limitations_to_be_a_list():
    """Present-but-empty is acceptable; absent or malformed is not. The
    field exists to make "nothing to disclose" an explicit statement
    rather than an omission.
    """
    validate_report(_report(limitations=[]))

    with pytest.raises(TypeError, match="must be a list"):
        validate_report(_report(limitations="none"))


def test_write_report_round_trips_and_is_deterministically_ordered(tmp_path):
    report = _report()

    path = write_report(report, directory=tmp_path)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "example-evaluation.json"
    assert loaded["results"] == report["results"]
    # Sorted keys so a regenerated report diffs only where values
    # actually changed.
    assert list(loaded) == sorted(loaded)


def test_write_report_refuses_to_write_an_invalid_report(tmp_path):
    report = _report()
    del report["source_commit"]

    with pytest.raises(ValueError):
        write_report(report, directory=tmp_path)

    assert not list(tmp_path.iterdir()), "an invalid report must not be written at all"


def test_committed_reports_satisfy_the_schema():
    """Guards the actual committed reports, not just the builder: a
    published report that no longer validates is a published claim with
    broken provenance.
    """
    from pathlib import Path

    reports_dir = Path("reports")
    if not reports_dir.exists():
        pytest.skip("no reports committed yet")

    committed = sorted(reports_dir.glob("*.json"))
    assert committed, "reports/ exists but contains no reports"
    for path in committed:
        validate_report(json.loads(path.read_text(encoding="utf-8")))
