"""Guards that keep the public documentation honest and readable.

These run in the normal test suite, so CI enforces them on every push to
``main`` and every pull request targeting ``main``. They do not need the
licensed dataset.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REPORTS = ROOT / "reports"

EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "site-packages", ".tox"}

MARKDOWN = sorted(
    p
    for p in ROOT.rglob("*.md")
    if not EXCLUDED_DIRS & set(p.parts)
)

# Lifecycle and course vocabulary. The documentation describes a finished
# system, so it names components rather than the order they were built in.
PROHIBITED = re.compile(r"(?i)\b(phases?|steps?|lessons?)\b")

# Wording that promises work which is already done.
STALE_FUTURE = re.compile(
    r"(?i)\b(once written|will be written|will be built|built next|"
    r"not yet implemented|to be implemented|coming in a later|will gain)\b"
)


def prose_of(text: str) -> str:
    """Markdown with fenced blocks and inline code removed."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


def md_id(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


@pytest.mark.parametrize("path", MARKDOWN, ids=md_id)
def test_markdown_is_utf8(path: pathlib.Path) -> None:
    path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", MARKDOWN, ids=md_id)
def test_no_lifecycle_vocabulary_in_prose(path: pathlib.Path) -> None:
    """No 'phase', 'step' or 'lesson' in rendered prose.

    Fenced blocks and inline code are exempt: they carry literal tool
    output and required syntax such as the GitHub Actions ``steps:`` key.
    """
    hits = PROHIBITED.findall(prose_of(path.read_text(encoding="utf-8")))
    assert not hits, f"{md_id(path)} uses lifecycle vocabulary: {sorted(set(hits))}"


@pytest.mark.parametrize("path", MARKDOWN, ids=md_id)
def test_no_stale_future_claims(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "architecture-decisions" in path.name:
        pytest.skip("dated historical log; future tense is correct in context")
    hits = STALE_FUTURE.findall(prose_of(text))
    assert not hits, f"{md_id(path)} promises finished work: {sorted(set(hits))}"


@pytest.mark.parametrize("path", MARKDOWN, ids=md_id)
def test_inline_code_is_not_split_across_lines(path: pathlib.Path) -> None:
    """A wrapped path or identifier renders with a space inside it."""
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    # Backticks pair in document order, so splitting on them makes every
    # odd-indexed segment a code span. Regex alternation would wrongly pair
    # one span's closing tick with the next span's opening tick, which turns
    # two adjacent links into a false positive.
    bad = []
    for span in text.split("`")[1::2]:
        if "\n" not in span:
            continue
        left, _, right = span.partition("\n")
        left, right = left.rstrip(), right.lstrip()
        if left and right and " " not in left and " " not in right:
            bad.append(f"{left}<newline>{right}")
    assert not bad, f"{md_id(path)} splits inline code across lines: {bad}"


@pytest.mark.parametrize("path", MARKDOWN, ids=md_id)
def test_relative_links_resolve(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    missing = []
    for match in re.finditer(r"\]\(([^)]+)\)", text):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (path.parent / target).resolve().exists():
            missing.append(target)
    assert not missing, f"{md_id(path)} links to missing paths: {missing}"


def test_every_published_report_is_valid_and_documented() -> None:
    """Each report parses, and carries the envelope readers rely on."""
    required = {"report_name", "provenance", "results", "metric_definitions", "limitations"}
    for report in sorted(REPORTS.glob("*.json")):
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert required <= doc.keys(), f"{report.name} missing {required - doc.keys()}"
        assert doc["limitations"], f"{report.name} declares no limitations"


def _fmt(value: float, spec: str) -> str:
    return format(value, spec)


NUMERIC_SYNC = [
    # (report, json path, format spec, document)
    ("explanation-evaluation.json", ("results", "attempted"), "d", "explanation-evaluation.md"),
    ("explanation-evaluation.json", ("results", "refused"), "d", "explanation-evaluation.md"),
    ("explanation-evaluation.json", ("results", "distinct_explanations"), "d", "explanation-evaluation.md"),
    ("retrieval-evaluation.json", ("results", "hit_rate_at_n"), ".4f", "retrieval-evaluation.md"),
]


@pytest.mark.parametrize(
    "report_name,keys,spec,doc_name",
    NUMERIC_SYNC,
    ids=[f"{r}:{'.'.join(k)}" for r, k, _, _ in NUMERIC_SYNC],
)
def test_documented_numbers_match_reports(report_name, keys, spec, doc_name) -> None:
    doc = json.loads((REPORTS / report_name).read_text(encoding="utf-8"))
    value = doc
    for key in keys:
        value = value[key]
    text = (DOCS / doc_name).read_text(encoding="utf-8")
    rendered = _fmt(value, spec)
    assert rendered in text, (
        f"{doc_name} does not contain {rendered} for "
        f"{report_name}:{'.'.join(keys)}; regenerate the table from the report"
    )


def test_explanation_metric_is_named_for_what_it_measures() -> None:
    """A lexical check must not be published as 'faithfulness'."""
    offenders = []
    for path in list(REPORTS.glob("*.json")) + MARKDOWN + list(
        (ROOT / "src").rglob("*.py")
    ):
        if "faithfulness_rate" in path.read_text(encoding="utf-8"):
            offenders.append(md_id(path))
    assert not offenders, f"'faithfulness_rate' survives in: {offenders}"


def test_review_register_tally_matches_its_headings() -> None:
    register = DOCS / "engineering-review-register.md"
    text = register.read_text(encoding="utf-8")
    headings = re.findall(r"^#{2,4} ([A-Z]+(?:-[A-Z0-9]+)+-\d+)", text, flags=re.MULTILINE)
    claimed = re.search(r"\*\*(\d+) primary findings\*\*", text)
    assert claimed, "register does not state a primary-finding tally"
    assert len(headings) == int(claimed.group(1)), (
        f"register lists {len(headings)} finding headings but claims "
        f"{claimed.group(1)}"
    )


def test_no_document_calls_a_used_split_untouched_or_final() -> None:
    """'untouched' is allowed only when denying it."""
    claims = re.compile(
        r"(?i)(reserved for final report|untouched final (?:split|estimate|evaluation) remains|"
        r"held untouched until (?:streaming replay and )?final|"
        r"`?validation`? (?:is|remains) untouched|`?replay`? (?:is|remains) untouched)"
    )
    denials = re.compile(
        r"(?i)(no longer untouched|never untouched|no untouched|not untouched|"
        r"would need to be carved|called it)"
    )
    offenders = []
    for path in MARKDOWN:
        for line in prose_of(path.read_text(encoding="utf-8")).splitlines():
            if claims.search(line) and not denials.search(line):
                offenders.append(f"{md_id(path)}: {line.strip()[:90]}")
    assert not offenders, "documents still claim an untouched split: " + "; ".join(offenders)


WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def test_documented_report_count_matches_the_reports_directory() -> None:
    """Prose that counts published reports must match what is committed."""
    actual = len(list(REPORTS.glob("*.json")))
    words = "|".join(WORD_NUMBERS)
    pattern = re.compile(
        rf"(?i)(?<![a-z])({words})\s+(?:published\s+)?reports(?![a-z])"
    )
    wrong = []
    for path in MARKDOWN:
        for match in pattern.finditer(prose_of(path.read_text(encoding="utf-8"))):
            claimed = WORD_NUMBERS[match.group(1).lower()]
            if claimed != actual:
                wrong.append(
                    f"{md_id(path)} says {match.group(0)!r}, "
                    f"but {actual} are committed"
                )
    assert not wrong, "; ".join(wrong)
