"""Checks the committed reports under `reports/` against the contract.

    python -m recommender.evaluation.generate_reports

This module used to *generate* those reports, by reading whatever JSON a
previous evaluation had left in `data/processed/` and stamping the
current commit and artifact manifest onto it. That could not tell a
result produced by the current code from one produced weeks and several
edits earlier -- the provenance it wrote was a guess with a hash on it.

Generation now belongs to the evaluations themselves
(`recommender.evaluation.publish`), which build a report while they still
hold their results. What remains here is the complementary check, and it
runs in CI on synthetic-free inputs because it reads only the committed
report files, never the licensed dataset: every published report must
still satisfy the current contract -- present provenance, a clean tree at
the time it was produced, no undefined metric, no null denominator.

A schema-version bump makes older reports fail here, which is intended:
it means they must be re-run rather than re-labelled.
"""

import json
import subprocess
import sys
from pathlib import Path

from recommender.evaluation.reports import PROJECT_ROOT, REPORTS_DIR, validate_report

EXPECTED_REPORTS = (
    "retrieval-evaluation",
    "end-to-end-evaluation",
    "tuning-decisions",
    "explanation-evaluation",
    "min-fresh-experiment",
    "baseline-evaluation",
    "ranking-evaluation",
    "reranking-evaluation",
    "ablation",
    "stage-comparison",
    "failure-analysis",
    "serving-latency",
    "durable-history-fallback",
)


def check_reports(directory: Path = REPORTS_DIR) -> list[str]:
    """Returns a list of problems; empty means every report is valid.

    An absent directory passes: nothing has been published, so there is
    no claim to verify. That is a real state -- it is what a tree looks
    like between a code change that invalidates the previous reports and
    the rerun that replaces them, and publishing the old ones under the
    new contract instead is precisely the mislabeling this check exists
    to prevent. A directory that exists must contain every expected
    report, valid; a partial set is a broken publication, not an
    unpublished one.
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    problems = []
    for name in EXPECTED_REPORTS:
        path = Path(directory) / f"{name}.json"
        if not path.exists():
            problems.append(f"{name}: no published report at {path}")
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            problems.append(f"{name}: not valid JSON ({error})")
            continue
        try:
            validate_report(report)
        except (ValueError, TypeError) as error:
            problems.append(f"{name}: {error}")
    return problems


def _is_shallow_clone() -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() == "true"
    except (subprocess.SubprocessError, OSError):
        return True  # can't tell -- treat as shallow, skip the check


def check_commits_are_real_ancestors(directory: Path = REPORTS_DIR) -> list[str]:
    """Each report's recorded `source_commit` must be a real commit that
    is actually reachable from `HEAD` -- not just a well-formed-looking
    hash.

    `validate_report`'s hash-format check (EVAL-PROVENANCE-58) rejects a
    string like "banana", but a syntactically valid 40-character hex
    string that simply never existed, or that belongs to some other
    unrelated history, would still pass it. This is the check that
    catches that: it needs the actual commit objects present, so it is
    a no-op on a shallow clone (the default for `actions/checkout`)
    rather than reporting false failures for commits genuinely present
    only in the fuller history a public reader might not have fetched.
    """
    directory = Path(directory)
    if not directory.exists() or _is_shallow_clone():
        return []

    problems = []
    for path in sorted(directory.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            commit = report["provenance"]["source_commit"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue  # already reported by check_reports
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=PROJECT_ROOT, capture_output=True, timeout=10, check=False,
        )
        if exists.returncode != 0:
            problems.append(f"{path.name}: source_commit {commit} does not exist in this repository")
            continue
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, timeout=10, check=False,
        )
        if ancestor.returncode != 0:
            problems.append(
                f"{path.name}: source_commit {commit} exists but is not an ancestor of HEAD"
            )
    return problems


def main() -> None:
    if not REPORTS_DIR.exists():
        print(
            f"no reports published at {REPORTS_DIR} -- nothing to verify. Reports are "
            "written by the evaluation that measures them, on a machine holding the "
            "licensed dataset."
        )
        return

    problems = check_reports()
    if problems:
        for problem in problems:
            print(f"INVALID  {problem}", file=sys.stderr)
        print(
            "\nReports are produced by the evaluation that measures them. To refresh "
            "one, commit your changes and re-run its module (for example "
            "`python -m recommender.evaluation.evaluate_retrieval`) on a machine that "
            "has the licensed dataset locally.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    for name in EXPECTED_REPORTS:
        print(f"valid    {name}")

    if _is_shallow_clone():
        print(
            "\nskipped  commit-ancestry check (shallow clone -- fetch full history "
            "to run it)"
        )
        return
    ancestry_problems = check_commits_are_real_ancestors()
    if ancestry_problems:
        for problem in ancestry_problems:
            print(f"INVALID  {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("valid    every recorded source_commit exists and is a real ancestor")


if __name__ == "__main__":
    main()
