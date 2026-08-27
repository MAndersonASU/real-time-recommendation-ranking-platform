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

# reports/ holds evaluation reports only. The build receipt describes
# artifacts rather than metrics and does not carry the evaluation-report
# envelope, so it lives under provenance/ and the report contract in
# recommender.evaluation.reports stays a single, unqualified rule.
NOT_AN_EVALUATION_REPORT: set[str] = set()


def evaluation_reports():
    return sorted(
        path
        for path in REPORTS.glob("*.json")
        if path.name not in NOT_AN_EVALUATION_REPORT
    )

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
    for report in evaluation_reports():
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
    ("ranking-evaluation.json", ("results", "ranked", "hit_rate_at_k"), ".4f", "ranking-evaluation.md"),
    ("ranking-evaluation.json", ("results", "ranked", "recall_at_k"), ".4f", "ranking-evaluation.md"),
    ("ranking-evaluation.json", ("results", "ranked", "ndcg_at_k"), ".4f", "ranking-evaluation.md"),
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "recall_at_k"), ".4f", "ranking-evaluation.md"),
    ("reranking-evaluation.json", ("results", "reranked", "recall_at_k"), ".4f", "reranking-evaluation.md"),
    ("reranking-evaluation.json", ("results", "ranked_only", "mean_distinct_categories"), ".2f", "reranking-evaluation.md"),
    ("reranking-evaluation.json", ("results", "reranked", "mean_distinct_categories"), ".2f", "reranking-evaluation.md"),
    ("stage-comparison.json", ("results", "retrieval", "hit_rate_at_k"), ".4f", "stage-comparison.md"),
    ("stage-comparison.json", ("results", "reranked", "recall_at_k"), ".4f", "stage-comparison.md"),
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
    matches = sorted(DOCS.rglob(doc_name))
    assert matches, f"{doc_name} not found under docs/"
    text = matches[0].read_text(encoding="utf-8")
    rendered = _fmt(value, spec)
    assert rendered in text, (
        f"{doc_name} does not contain {rendered} for "
        f"{report_name}:{'.'.join(keys)}; regenerate the table from the report"
    )


def test_explanation_metric_is_named_for_what_it_measures() -> None:
    """A lexical check must not be published as 'faithfulness'."""
    offenders = []
    for path in evaluation_reports() + MARKDOWN + list(
        (ROOT / "src").rglob("*.py")
    ):
        if "faithfulness_rate" in path.read_text(encoding="utf-8"):
            offenders.append(md_id(path))
    assert not offenders, f"'faithfulness_rate' survives in: {offenders}"


def test_review_register_tally_matches_its_headings() -> None:
    register = next(DOCS.rglob("engineering-review-register.md"))
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
    """Prose that counts published reports must match what is committed.

    Two shapes are checked. "The four published reports" is caught by a
    tight number-then-"reports" pattern. That alone missed the real bug
    found in this repository: "the four machine-readable reports
    currently in `reports/`", where an adjective sits between the
    number and "reports". A second pattern matches that specific shape
    -- a number, then "reports", then "currently in" a literal
    `reports/` reference -- rather than broadening the tight pattern in
    general, which reintroduces false positives ("one JSON per
    published report" is a per-report count, not a total).
    """
    actual = len(evaluation_reports())
    words = "|".join(WORD_NUMBERS)
    tight = re.compile(rf"(?i)(?<![a-z])({words})\s+(?:published\s+)?reports?(?![a-z])")
    currently_in_directory = re.compile(
        rf"(?i)(?<![a-z])({words})\s+(?:[a-z][a-z-]*\s+){{0,4}}reports?\s+"
        rf"(?:[a-z][a-z-]*\s+){{0,4}}currently\s+in\s+`?reports/?`?"
    )

    wrong = []
    for path in MARKDOWN:
        text = prose_of(path.read_text(encoding="utf-8"))
        for pattern in (tight, currently_in_directory):
            for match in pattern.finditer(text):
                claimed = WORD_NUMBERS[match.group(1).lower()]
                if claimed != actual:
                    wrong.append(
                        f"{md_id(path)} says {match.group(0)!r}, but {actual} are committed"
                    )
    assert not wrong, "; ".join(sorted(set(wrong)))
