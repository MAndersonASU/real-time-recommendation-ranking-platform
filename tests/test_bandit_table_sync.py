"""BANDIT-REVIEW-65: `docs/engineering-review-and-hardening.md`'s Bandit
table claimed low-severity findings were "reviewed by category," but
listed only 3 of the 6 real files carrying a B404/B603/B607 finding --
found by actually re-running Bandit against the checked-out source, not
by re-reading the table. This runs the same real scan and checks the
table's own file list against it, so the next new subprocess call site
fails this test instead of silently falling out of the table again.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "engineering-review-and-hardening.md"


def _run_bandit() -> dict:
    # `-o <file>`, not stdout: a plain `-f json` with no `-o` also
    # writes a "Working... 100%" progress line to stdout ahead of the
    # JSON, corrupting it for a parser expecting JSON alone.
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "bandit.json"
        subprocess.run(
            [sys.executable, "-m", "bandit", "-r", "src/recommender", "-f", "json", "-o", str(out_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            # Bandit's own exit code is 1 whenever it finds anything at
            # all (by design -- that's how `bandit -ll` gates CI), so a
            # non-zero code here is expected and not itself a failure.
        )
        return json.loads(out_path.read_text(encoding="utf-8"))


def _files_with_test_id(data: dict, test_id: str) -> set[str]:
    # Bandit reports `filename` relative to the cwd it was run from
    # (REPO_ROOT here, so "src/recommender/..."); the doc table names
    # files relative to `src/recommender/` instead (e.g.
    # "monitoring/artifact_manifest.py"), so that prefix is stripped
    # here to compare like with like.
    return {
        Path(r["filename"]).as_posix().removeprefix("src/recommender/")
        for r in data["results"]
        if r["test_id"] == test_id
    }


def _doc_files_for_row(prefix: str) -> set[str]:
    """Extracts the backtick-quoted file paths from the table row whose
    ID cell starts with `prefix` (e.g. "B404").
    """
    text = DOC_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("|") and prefix in line.split("|")[1]:
            cells = line.split("|")
            return set(re.findall(r"`([^`]+)`", cells[2]))
    raise AssertionError(f"no table row found whose ID cell contains {prefix!r}")


def test_bandit_subprocess_table_lists_every_file_with_a_real_finding():
    data = _run_bandit()
    real_files = (
        _files_with_test_id(data, "B404")
        | _files_with_test_id(data, "B603")
        | _files_with_test_id(data, "B607")
    )
    documented_files = {
        f.replace("\\", "/") for f in _doc_files_for_row("B404")
    }

    missing = real_files - documented_files
    assert not missing, (
        f"Bandit found B404/B603/B607 in these files, but the table in "
        f"{DOC_PATH.relative_to(REPO_ROOT)} does not list them: {sorted(missing)}"
    )


def test_no_assert_used_outside_tests():  # B101
    """The direct regression guard for the fix itself: assert compiled
    out under `python -O` let a real evaluation invariant silently stop
    being checked. `tests/` is exempt (pytest's own assertion rewriting
    is the point there); production code under `src/` must not use a
    bare `assert` for anything that has to hold at runtime.

    Parses the AST rather than grepping for the word "assert" -- this
    file's own module docstring and several inline comments legitimately
    discuss `assert` as a concept while explaining why it was removed,
    which a text search would misreport as a live offender.
    """
    import ast

    offenders = []
    for path in sorted((REPO_ROOT / "src" / "recommender").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"these use a bare `assert` in production code, which `python -O` compiles "
        f"out entirely -- use an explicit exception instead: {offenders}"
    )
