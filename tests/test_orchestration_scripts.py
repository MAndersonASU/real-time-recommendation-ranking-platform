"""Guards against `evaluate_all.sh` and `rebuild.sh` silently drifting from
what they claim to do.

REPRO-ORCHESTRATION-59: `evaluate_all.sh` used to run 7 of the 12 published
evaluations while its own header comment claimed "every evaluation whose
report is published", and both scripts hardcoded the Windows venv layout
despite the README documenting macOS/Linux setup too. These tests fail
the moment either script's declared coverage stops matching reality,
instead of that drifting silently the way it did before.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from recommender.evaluation.generate_reports import EXPECTED_REPORTS

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATE_ALL = REPO_ROOT / "evaluate_all.sh"
REBUILD = REPO_ROOT / "rebuild.sh"
REPORTS_DIR = REPO_ROOT / "reports"

# Every module invoked by evaluate_all.sh maps to exactly one published
# report name. Keeping this map here, rather than trusting the script's
# own step labels, is the point: a report added to EXPECTED_REPORTS
# without a matching line in the map (or the script) fails loudly.
MODULE_TO_REPORT = {
    "recommender.evaluation.evaluate_retrieval": "retrieval-evaluation",
    "recommender.evaluation.evaluate_end_to_end": "end-to-end-evaluation",
    "recommender.evaluation.verify_tuning_decisions": "tuning-decisions",
    "recommender.evaluation.evaluate_explanations": "explanation-evaluation",
    "recommender.evaluation.min_fresh_experiment": "min-fresh-experiment",
    "recommender.evaluation.evaluate_baseline": "baseline-evaluation",
    "recommender.evaluation.evaluate_ranking": "ranking-evaluation",
    "recommender.evaluation.evaluate_reranking": "reranking-evaluation",
    "recommender.evaluation.ablations": "ablation",
    "recommender.evaluation.stage_comparison": "stage-comparison",
    "recommender.evaluation.failure_analysis": "failure-analysis",
    "recommender.serving.verify_latency": "serving-latency",
}


def _invoked_modules(script_text: str) -> list[str]:
    return re.findall(r"-m\s+(recommender\.[\w.]+)", script_text)


def test_module_to_report_map_covers_every_expected_report():
    # A stale test fixture would defeat the point of the test below --
    # this catches the map itself falling out of sync with the contract.
    assert set(MODULE_TO_REPORT.values()) == set(EXPECTED_REPORTS)


def test_evaluate_all_runs_every_published_evaluation():
    text = EVALUATE_ALL.read_text(encoding="utf-8")
    invoked = _invoked_modules(text)

    unknown = [m for m in invoked if m not in MODULE_TO_REPORT]
    assert not unknown, f"evaluate_all.sh invokes unmapped module(s): {unknown}"

    covered_reports = {MODULE_TO_REPORT[m] for m in invoked}
    missing = set(EXPECTED_REPORTS) - covered_reports
    assert not missing, f"evaluate_all.sh never runs the evaluation(s) for: {sorted(missing)}"


def test_evaluate_all_covers_every_currently_committed_report():
    # Belt-and-suspenders alongside the EXPECTED_REPORTS check above: this
    # one compares against the actual files under reports/, so it also
    # catches EXPECTED_REPORTS itself having drifted from what is really
    # committed.
    committed = {path.stem for path in REPORTS_DIR.glob("*.json")}
    invoked = _invoked_modules(EVALUATE_ALL.read_text(encoding="utf-8"))
    covered_reports = {MODULE_TO_REPORT[m] for m in invoked if m in MODULE_TO_REPORT}
    missing = committed - covered_reports
    assert not missing, f"evaluate_all.sh never runs the evaluation(s) for: {sorted(missing)}"


def test_evaluate_all_invokes_each_module_exactly_once():
    invoked = _invoked_modules(EVALUATE_ALL.read_text(encoding="utf-8"))
    duplicates = {m for m in invoked if invoked.count(m) > 1}
    assert not duplicates, f"evaluate_all.sh runs these more than once: {duplicates}"


def test_rebuild_builds_the_fit_only_bundle():
    # verify_tuning_decisions (wired into evaluate_all.sh) silently falls
    # back to a leakage-contaminated comparison when these two artifacts
    # are absent -- a rebuild that skips them produces a report that
    # *looks* the same shape but is quietly worse evidence.
    text = REBUILD.read_text(encoding="utf-8")
    invoked = _invoked_modules(text)
    assert "recommender.retrieval.train_fit_only" in invoked
    assert "recommender.ranking.build_dataset_fit_only" in invoked


@pytest.mark.parametrize("script", [EVALUATE_ALL, REBUILD])
def test_script_detects_venv_layout_instead_of_hardcoding_one(script):
    text = script.read_text(encoding="utf-8")
    assert ".venv/Scripts/python.exe" in text, "missing the Windows venv layout"
    assert ".venv/bin/python" in text, "missing the macOS/Linux venv layout"
    # A single unconditional `PY=...` assignment would mean only one of
    # the two layouts above is ever actually selected at runtime.
    assert not re.search(r'^PY="\./.venv/Scripts/python\.exe"\s*$', text, re.MULTILINE)


@pytest.mark.parametrize("script", [EVALUATE_ALL, REBUILD])
def test_script_is_syntactically_valid_bash(script):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    result = subprocess.run(
        [bash, "-n", str(script)], capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr
