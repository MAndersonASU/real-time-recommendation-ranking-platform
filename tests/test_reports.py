import json

import pytest

from recommender.evaluation.reports import (
    REPORT_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    ReportProvenanceError,
    _metric_leaves,
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


def test_the_clean_tree_check_ignores_the_reports_directory(monkeypatch):
    """A full evaluation pass publishes four reports. If writing the
    first one dirtied the tree, the second would refuse -- the check
    would be blocking correct behaviour instead of stale code. Only
    `reports/` is exempt, and the exemption is expressed to git rather
    than by filtering afterwards, so a path that merely mentions
    "reports" elsewhere is not accidentally covered.
    """
    import recommender.evaluation.reports as reports_module

    seen = {}

    def fake_git(*args):
        seen["args"] = args
        return ""

    monkeypatch.setattr(reports_module, "_git", fake_git)

    assert reports_module.working_tree_is_clean() is True
    assert ":(exclude)reports" in seen["args"]


def test_an_unavailable_git_is_treated_as_dirty(monkeypatch):
    """Failing closed. If the tree's state cannot be established, a
    report claiming a clean one would be an unverified assertion.
    """
    import recommender.evaluation.reports as reports_module

    monkeypatch.setattr(reports_module, "_git", lambda *_a: None)

    assert reports_module.working_tree_is_clean() is False


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


@pytest.mark.parametrize(
    "bad_commit",
    [
        "banana",
        "0" * 39,  # one char short
        "0" * 41,  # one char long
        "g" * 40,  # not hex
        ("a1b2c3d4e5" * 4).upper(),  # a real hash's length, wrong case
        123,
    ],
    ids=["not-hex-like", "too-short", "too-long", "non-hex-chars", "uppercase", "not-a-string"],
)
def test_validate_rejects_a_malformed_source_commit(bad_commit):
    """EVAL-PROVENANCE-58: a nonempty value used to be accepted outright.
    `GIT_COMMIT_SHA=banana` made this exact string reach a published
    report and pass validation -- checked here directly, not just via
    the resolver, so a future validator regression is caught even if
    something else constructs a report by hand.
    """
    report = _report()
    report["provenance"]["source_commit"] = bad_commit

    with pytest.raises(ValueError, match="hex commit hash"):
        validate_report(report)


def test_source_commit_ignores_git_commit_sha_env_var(monkeypatch):
    """EVAL-PROVENANCE-58: an evaluation report's provenance must always
    reflect the real repository state, never a caller-supplied
    environment variable. `GIT_COMMIT_SHA` remains correct for
    recommender.monitoring.artifact_manifest and
    recommender.tracking.experiment_log, which run inside containers
    with no `.git` directory to discover a commit from -- this
    function is not that case.
    """
    from recommender.evaluation import reports as reports_module

    real_commit = reports_module._git("rev-parse", "HEAD")
    monkeypatch.setenv("GIT_COMMIT_SHA", "banana")

    assert reports_module.source_commit() == real_commit
    assert reports_module.source_commit() != "banana"


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


# --- nested definition enforcement -------------------------------------

def _nested_report(**overrides):
    report = _report(
        results={
            "diversity_cap": {
                "decision_confirmed": True,
                "cap_value_comparison": {
                    "by_cap_value": {"3": {"mean_slate_relevance": 0.42}},
                },
            }
        },
        metric_definitions={
            "diversity_cap": "the cap comparison",
            "decision_confirmed": "whether the original call held up",
            "mean_slate_relevance": "mean predicted relevance of a slate",
        },
    )
    report.update(overrides)
    return report


def test_a_nested_metric_needs_a_definition_too():
    """The gap this closes.

    Only top-level section names were compared against the definitions,
    so an invented field several levels down -- `made_up_score` -- was
    published without anyone having said what it measures. Almost every
    tuning metric lives at that depth.
    """
    report = _nested_report()
    report["results"]["diversity_cap"]["made_up_score"] = 0.5

    with pytest.raises(ValueError, match="no definition"):
        validate_report(report)


def test_a_metric_inside_a_comparison_table_needs_a_definition():
    """Deeper still: values inside a by-value comparison table."""
    report = _nested_report()
    report["results"]["diversity_cap"]["cap_value_comparison"]["by_cap_value"]["3"][
        "undocumented_thing"
    ] = 1.0

    with pytest.raises(ValueError, match="undocumented_thing"):
        validate_report(report)


def test_comparison_table_keys_are_not_treated_as_metrics():
    """A table keyed by the value being compared -- budgets "0.90", caps
    "3", depths "1000" -- names coordinates, not measurements. Demanding
    a definition for each would mean defining every number anyone
    compares.
    """
    report = _nested_report()
    report["results"]["diversity_cap"]["cap_value_comparison"]["by_cap_value"]["5"] = {
        "mean_slate_relevance": 0.4
    }

    validate_report(report)  # must not raise


def test_known_metadata_is_not_treated_as_a_metric():
    report = _nested_report()
    report["results"]["diversity_cap"]["sampling"] = {
        "seed": 1,
        "selected_ids_sha256": "0" * 64,
        "anything_inside_here": 123,
    }
    report["results"]["diversity_cap"]["selection_rule"] = "largest cap within budget"

    validate_report(report)  # must not raise


def test_every_committed_report_defines_every_nested_metric():
    """Guards the real reports, not just the rule."""
    import json
    from pathlib import Path

    reports_dir = Path("reports")
    if not reports_dir.exists():
        pytest.skip("no reports committed yet")

    for path in sorted(reports_dir.glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        undefined = _metric_leaves(report["results"]) - set(report["metric_definitions"])
        assert not undefined, f"{path.name} publishes undefined metrics: {sorted(undefined)}"


# --- fit-only provenance -----------------------------------------------

def _leakage_free_report(**bundle_overrides):
    bundle = {
        "retrieval_model_sha256": "a" * 64,
        "content_artifact_sha256": "b" * 64,
        "bundle_manifest_sha256": "c" * 64,
        "ranking_feature_table_sha256": "d" * 64,
        "train_report_sha256": "e" * 64,
        "tune_fold_seed": 20260823,
        "tune_fold_fraction": 0.2,
        "training_seed": 42,
        "embedding_dim": 32,
    }
    bundle.update(bundle_overrides)
    report = _report(
        results={"diversity_cap": {"feature_provenance": {"tune_fold_leakage": False}}},
        metric_definitions={"diversity_cap": "the cap comparison"},
    )
    report["artifacts"]["fit_only_bundle"] = bundle
    return report


def test_a_leakage_free_claim_with_full_hashes_is_accepted():
    validate_report(_leakage_free_report())  # must not raise


@pytest.mark.parametrize(
    "bad", ["absent", "", "abc123", "A" * 64, "z" * 64, None, 12345]
)
def test_a_leakage_free_claim_needs_a_real_hash(bad):
    """`tune_fold_leakage: false` says a model never saw the fold. That
    is only checkable if the report identifies the model. "absent" was
    accepted here, so the report's strongest claim could be published
    with nothing behind it.
    """
    with pytest.raises((ValueError, TypeError)):
        validate_report(_leakage_free_report(retrieval_model_sha256=bad))


def test_a_leakage_free_claim_needs_the_bundle_at_all():
    report = _leakage_free_report()
    del report["artifacts"]["fit_only_bundle"]

    with pytest.raises(ValueError, match="no fit_only_bundle"):
        validate_report(report)


def test_a_leaked_run_is_not_required_to_carry_a_fit_only_bundle():
    """A run that used the deployed table reports the leakage honestly
    and has no fit-only artifacts to name. Requiring them would force a
    manifest describing artifacts that were never built.
    """
    report = _report(
        results={"diversity_cap": {"feature_provenance": {"tune_fold_leakage": True}}},
        metric_definitions={"diversity_cap": "the cap comparison"},
    )

    validate_report(report)  # must not raise


def test_the_fold_description_must_describe_a_fold():
    with pytest.raises(ValueError, match="does not describe a fold"):
        validate_report(_leakage_free_report(tune_fold_fraction=1.5))
