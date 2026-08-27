"""Construction-era vocabulary must not survive in developer-facing source.

`tests/test_documentation.py` already bans "phase", "step" and "lesson"
from rendered Markdown prose. That check has no reach into `.py` files,
so the same construction-era language -- "Phase 6's in-process
UserState", "matching the lesson's quick check" -- persisted in source
comments, docstrings and log notes across a dozen files, invisible to
every documentation guard.

This checks source for "phase"/"phases" in any form -- not just the
numbered "Phase <number>" shape, which a first version of this guard
matched exclusively. Four real occurrences slipped past that narrower
pattern precisely because they had no trailing number ("every earlier
phase already reads", "this phase's own requirement", "exactly the
phase's named path", "specifically for this phase") -- generic
construction-sequence wording is exactly as much a problem unnumbered
as it is numbered, so the bare word is what is actually banned now, the
same way the Markdown guard already bans it. "lesson"/"lessons" is
banned the same way. "step" is deliberately not banned here the way it
is in Markdown: it is a legitimate identifier in source
(`optimizer.step()`, a `training_step` counter, a GitHub Actions
`steps:` key) far more often than it is construction narration, so
banning it in code would need a much more selective check than banning
"phase" and "lesson" does.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}

PHASE = re.compile(r"(?i)\bphases?\b")
LESSON = re.compile(r"(?i)\blessons?\b")

# Exact (file, pattern-name) pairs where the word is being discussed,
# not used -- test_documentation.py's own guard has to name "lesson" and
# "phase" to describe what it bans, and this file's own docstring and
# fixtures have to name them too. Narrow and enumerated, not a
# directory or file-wide exemption.
ACCEPTED_MENTIONS: frozenset[tuple[str, str]] = frozenset({
    ("tests/test_documentation.py", "lesson"),
    ("tests/test_documentation.py", "phase"),
    ("tests/test_source_vocabulary.py", "lesson"),
    ("tests/test_source_vocabulary.py", "phase"),
})


def _python_files() -> list[pathlib.Path]:
    files = []
    for base in (ROOT / "src", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if not (EXCLUDED_DIRS & set(path.parts)):
                files.append(path)
    return sorted(files)


PYTHON_FILES = _python_files()


def _rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


@pytest.mark.parametrize("path", PYTHON_FILES, ids=_rel)
def test_no_phase_references(path: pathlib.Path) -> None:
    """No 'phase'/'phases' in source, numbered or not."""
    if (_rel(path), "phase") in ACCEPTED_MENTIONS:
        pytest.skip("this file discusses the banned word, rather than using it")
    text = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in PHASE.finditer(text)]
    assert not hits, f"{_rel(path)} still references {hits}"


@pytest.mark.parametrize("path", PYTHON_FILES, ids=_rel)
def test_no_lesson_references(path: pathlib.Path) -> None:
    """No 'lesson'/'lessons' in source."""
    if (_rel(path), "lesson") in ACCEPTED_MENTIONS:
        pytest.skip("this file discusses the banned word, rather than using it")
    text = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in LESSON.finditer(text)]
    assert not hits, f"{_rel(path)} still references {hits}"


@pytest.mark.parametrize(
    "sample",
    [
        "Phase 6's in-process UserState",
        "used since Phase 8, not a second path",
        "matching the lesson's quick check",
        "a worked example of the lessons learned",
        "every earlier phase already reads this file",
        "this phase's own requirement is an explicit refusal",
        "exactly the phase's named path",
        "held untouched from the start specifically for this phase",
    ],
    ids=[
        "phase-with-number",
        "phase-with-number-possessive",
        "lesson-possessive",
        "lessons-plural",
        "bare-phase-no-number-1",
        "bare-phase-no-number-2",
        "bare-phase-no-number-3",
        "bare-phase-no-number-4",
    ],
)
def test_banned_patterns_are_detected(sample: str) -> None:
    """Both patterns fire on the exact shapes this pass found -- including
    the four bare, unnumbered "phase" occurrences a narrower first
    version of this guard let through.
    """
    assert PHASE.search(sample) or LESSON.search(sample), sample


@pytest.mark.parametrize(
    "sample",
    [
        "optimizer.step()",
        "a training-step counter increments once per batch",
        "steps:\n  - uses: actions/checkout@v4",
        "the ranking model's own five features",
    ],
)
def test_legitimate_step_usage_is_not_flagged(sample: str) -> None:
    """'step' alone, in any legitimate technical shape, is never banned
    here -- only 'phase'/'phases' and 'lesson'/'lessons' are.
    """
    assert not PHASE.search(sample)
    assert not LESSON.search(sample)
