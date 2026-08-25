import json

import pytest

from recommender.evaluation.reports import (
    REPORT_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    ReportProvenanceError,
    build_report,
    validate_report,
    write_report,
)


def _report(**overrides):
    # require_clean_tree is off here and only here: these tests build
    # reports from a working tree that is, by definition, being edited.
    # The refusal itself is covered by its own test below.
    report = build_report(
        report_name="example-evaluation",
        evaluation_module="recommender.evaluation.example",
        dataset={"name": "MIND small", "split": "validation", "edition": "2019-11"},
        configuration={"k": 10, "seed": 42},
        sampling={"method": "seeded uniform random without replacement", "seed": 7},
        denominators={"impressions_evaluated": 2000, "users": 1500},
        metric_definitions={
            "hit_rate_at_k": "share of impressions whose clicked item is in the top K"
        },
        results={"hit_rate_at_k": 0.0145},
        limitations=["retrieval remains the binding constraint"],
        require_clean_tree=False,
    )
    # Every test below asserts against a report that is valid apart from
    # the one thing it is testing, so the baseline must satisfy the
    # clean-tree rule regardless of the tree these tests run in.
    report["provenance"]["working_tree_clean"] = True
    report["provenance"]["source_commit"] = "0" * 40
    report.update(overrides)
    return report


def test_a_built_report_carries_full_provenance():
    report = _report()

    for field in REQUIRED_FIELDS:
        assert field in report, field

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["provenance"]["generated_at"].endswith("+00:00")
    assert report["provenance"]["evaluation_module"] == "recommender.evaluation.example"
    # Ties the numbers to the exact artifacts that produced them, so a
    # later artifact change shows up as a changed hash rather than an
    # unexplained metric shift.
    assert "retrieval_model_sha256_prefix" in report["artifacts"]
    assert "serving_code_commit" in report["artifacts"]


def test_building_from_a_dirty_tree_is_refused():
    """The defect this closes: a report used to be assembled after the
    fact and stamped with whatever commit was checked out at publishing
    time. From a modified tree that commit describes code that is not
    what ran, so the report looks attributable while being unverifiable.
    Refusing is the only honest option -- a warning would be recorded and
    ignored.
    """
    import recommender.evaluation.reports as reports_module

    original = reports_module.working_tree_is_clean
    reports_module.working_tree_is_clean = lambda: False
    try:
        with pytest.raises(ReportProvenanceError, match="dirty working tree"):
            build_report(
                report_name="example-evaluation",
                evaluation_module="recommender.evaluation.example",
                dataset={},
                configuration={},
                sampling={"method": "full"},
                denominators={"n": 1},
                metric_definitions={"hit_rate_at_k": "x"},
                results={"hit_rate_at_k": 0.5},
                limitations=[],
            )
    finally:
        reports_module.working_tree_is_clean = original


def test_validate_accepts_a_well_formed_report():
    validate_report(_report())  # must not raise


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_validate_rejects_a_report_missing_any_required_field(field):
    report = _report()
    del report[field]

    with pytest.raises(ValueError, match="missing required fields"):
        validate_report(report)


def test_validate_rejects_a_report_whose_tree_was_dirty():
    report = _report()
    report["provenance"]["working_tree_clean"] = False

    with pytest.raises(ValueError, match="dirty working tree"):
        validate_report(report)


def test_validate_rejects_a_report_with_no_source_commit():
    report = _report()
    report["provenance"]["source_commit"] = None

    with pytest.raises(ValueError, match="no source commit"):
        validate_report(report)


def test_validate_rejects_a_metric_with_no_definition():
    """A number with no stated definition is not a result, it is a
    number. `recall@k` in particular has several defensible definitions
    that differ by a factor of the clicked-item count.
    """
    report = _report(results={"hit_rate_at_k": 0.1, "mystery_metric": 0.3})

    with pytest.raises(ValueError, match="no definition"):
        validate_report(report)


def test_validate_rejects_a_null_denominator():
    """A rate whose denominator is null cannot be interpreted at all --
    0.0 out of nothing and 0.0 out of 50,000 are different claims.
    """
    report = _report(denominators={"impressions_evaluated": None})

    with pytest.raises(ValueError, match="must not be null"):
        validate_report(report)


def test_validate_rejects_a_rate_outside_its_own_range():
    report = _report(results={"hit_rate_at_k": 1.4})

    with pytest.raises(ValueError, match="is a rate"):
        validate_report(report)


def test_validate_requires_a_sampling_description():
    """Absent sampling used to mean "assume it read everything". It also
    silently covered a `head(N)` selection that read the earliest rows
    only, which is not a sample of anything.
    """
    with pytest.raises(ValueError, match="how its sample was selected"):
        validate_report(_report(sampling={}))


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
    del report["provenance"]

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
