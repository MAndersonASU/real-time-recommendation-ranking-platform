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


_REGISTER_STATUS_CATEGORIES = (
    ("verified closed", "Verified closed"),
    ("partially closed", "Partially closed by scope"),
    ("accepted limitation", "Accepted limitations"),
    ("open", "Open"),
)


def test_review_register_status_tally_is_accurate() -> None:
    """REVIEW-STATUS-TALLY: the register's own narrative said all 34
    findings were verified closed while its actual per-finding
    `**Status**` fields held 31 verified closed, 1 partially closed, 2
    accepted limitations. This parses every primary finding's own
    `**Status**` field directly -- not a heading count, and not a
    hand-maintained summary sentence that can drift from the entries it
    claims to summarize -- and checks it against the register's own
    "Current aggregate status" section, so the two can never silently
    disagree again.
    """
    register = next(DOCS.rglob("engineering-review-register.md"))
    text = register.read_text(encoding="utf-8")

    findings = re.findall(
        r"^## [A-Z]+(?:-[A-Z0-9]+)+-\d+[^\n]*\n\*\*Severity\*\* [^\n]*?\*\*Status\*\* ([^\n]+)$",
        text,
        flags=re.MULTILINE,
    )
    assert findings, "no primary findings with a parseable Status field were found"

    actual: dict[str, int] = {label: 0 for _, label in _REGISTER_STATUS_CATEGORIES}
    unrecognized = []
    for status in findings:
        for prefix, label in _REGISTER_STATUS_CATEGORIES:
            if status.lower().startswith(prefix):
                actual[label] += 1
                break
        else:
            unrecognized.append(status)
    assert not unrecognized, f"finding(s) with an unrecognized status category: {unrecognized}"

    claimed = {}
    for _, label in _REGISTER_STATUS_CATEGORIES:
        match = re.search(rf"- \*\*{re.escape(label)}:\*\* (\d+)", text)
        assert match, f"'Current aggregate status' does not state a count for {label!r}"
        claimed[label] = int(match.group(1))

    total_match = re.search(r"- \*\*Total primary findings:\*\* (\d+)", text)
    assert total_match, "'Current aggregate status' does not state a total"

    assert actual == claimed, (
        f"parsed per-finding status counts {actual} do not match the 'Current "
        f"aggregate status' section's claimed counts {claimed}"
    )
    assert sum(actual.values()) == int(total_match.group(1)) == len(findings)


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
    "thirteen": 13,
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


_DOCKER_COMPOSE_UP_LINE = re.compile(r"docker compose up\b[^#\n]*")


def test_a_command_claiming_to_start_redis_actually_names_the_service() -> None:
    """Regression test for a real bug: README.md's containerized-demo
    command was commented "API + its Redis dependency" while the actual
    `docker compose up -d --build api` command named only `api` --
    Redis has no `depends_on` relationship with the API service
    (DEPLOYMENT-CONTRACT-62 in the register), so that comment was simply
    false. A command line's own trailing comment claiming Redis starts
    must name `redis` as one of the services the command actually
    passes, not merely say so in prose.
    """
    offenders = []
    for path in MARKDOWN:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _DOCKER_COMPOSE_UP_LINE.search(line)
            if match is None:
                continue
            comment = line[match.end():]
            if not re.search(r"(?i)\bredis\b", comment):
                continue
            command = match.group(0)
            services = command.split("--build", 1)[-1].split()
            if "redis" not in services:
                offenders.append(f"{md_id(path)}: {line.strip()!r}")
    assert not offenders, (
        "a command's own comment claims Redis starts, but the command does not "
        f"name the redis service: {offenders}"
    )


def test_every_committed_report_appears_in_the_evaluation_index() -> None:
    """docs/evaluation.md is the map of every published report -- a
    report present in reports/ but missing from that page's index is
    real evidence nobody can find without already knowing the filename.
    Regression test for exactly this gap: tuning-decisions.json and
    min-fresh-experiment.json were both committed, validated reports
    with no row on this page at all.
    """
    evaluation_md = next(p for p in MARKDOWN if md_id(p) == "docs/evaluation.md")
    text = evaluation_md.read_text(encoding="utf-8")

    missing = [
        report.name for report in evaluation_reports() if report.name not in text
    ]
    assert not missing, f"docs/evaluation.md does not reference: {sorted(missing)}"


# The item-tower content-vector fix improved the four relevance metrics
# (hit rate, recall, NDCG, MRR) by 7.6x-13.5x, but catalog coverage --
# also a real retrieval metric, shown in the same results table -- only
# improved 1.5x. A blanket "every retrieval metric improved 7.6x-13.5x"
# is false of the metric sitting right next to that claim.
BLANKET_RETRIEVAL_IMPROVEMENT_CLAIM = re.compile(
    r"(?i)\b(every|all)\b[^.]{0,40}retrieval\s+metric[^.]{0,60}"
    r"\b7\.6x[^.]{0,20}13\.5x"
)


def test_no_blanket_retrieval_improvement_claim() -> None:
    """'Every/all retrieval metric improved 7.6x-13.5x' must not appear.

    Catalog coverage improved by 1.5x, not 7.6x-13.5x -- the correct
    wording distinguishes "the four relevance metrics" from catalog
    coverage rather than claiming every retrieval metric moved together.
    """
    offenders = []
    for path in MARKDOWN:
        text = prose_of(path.read_text(encoding="utf-8"))
        for match in BLANKET_RETRIEVAL_IMPROVEMENT_CLAIM.finditer(text):
            offenders.append(f"{md_id(path)}: {match.group(0)!r}")
    assert not offenders, "; ".join(offenders)


# TIMESTAMP-CONTRACT-64, documentation-terminology finding: RFC3339
# itself permits a lowercase "t"/"z" as a case-insensitive alternate to
# "T"/"Z" (see recommender.streaming.schema's top-of-file comment, right
# above `_RFC3339_RE`); only this project's own narrower canonical
# profile excludes them. A claim that RFC3339 itself excludes a
# lowercase separator previously appeared in both the validator's own
# docstring and its test suite, contradicting that same top-of-file
# comment.
RFC3339_LOWERCASE_EXCLUSION_MISATTRIBUTION = re.compile(
    r"(?i)RFC\s*3339[^.]{0,100}exclud[a-z]*[^.]{0,60}lowercase"
)

PYTHON_SOURCE = [
    path
    for path in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py"))
    # This file's own guard below deliberately contains the banned
    # wording as a comment and as a fixture string proving the pattern
    # fires, which is not a real documentation claim to flag.
    if path.name != "test_documentation.py"
]


def test_no_rfc3339_lowercase_exclusion_misattribution() -> None:
    """RFC3339 permits lowercase 't'/'z'; only this project's own
    canonical profile excludes them. Guards against
    TIMESTAMP-CONTRACT-64's documentation-terminology gap reappearing
    in prose, docstrings, comments or test names.
    """
    offenders = []
    for path in list(MARKDOWN) + PYTHON_SOURCE:
        text = path.read_text(encoding="utf-8")
        text = prose_of(text) if path in MARKDOWN else text
        for match in RFC3339_LOWERCASE_EXCLUSION_MISATTRIBUTION.finditer(text):
            offenders.append(f"{md_id(path)}: {match.group(0)!r}")
    assert not offenders, (
        "misattributes lowercase t/z exclusion to RFC3339 itself, rather "
        "than to this project's own narrower profile: " + "; ".join(offenders)
    )


def test_rfc3339_lowercase_exclusion_misattribution_pattern_fires() -> None:
    """The pattern above actually catches the exact wording this pass
    found and corrected in schema.py and test_streaming_schema.py, and
    does not fire on the corrected wording that replaced it.
    """
    broken = (
        'fromisoformat accepts several ISO 8601 forms RFC3339\'s own '
        'grammar excludes (omitted seconds, a lowercase "t"/"z").'
    )
    assert RFC3339_LOWERCASE_EXCLUSION_MISATTRIBUTION.search(broken)

    fixed = (
        "forms RFC3339's own grammar genuinely excludes (a space instead "
        'of "T", omitted seconds), and forms RFC3339 itself permits as '
        "a case-insensitive alternate but this project's narrower "
        'canonical profile intentionally does not (a lowercase "t"/"z").'
    )
    assert not RFC3339_LOWERCASE_EXCLUSION_MISATTRIBUTION.search(fixed)


def test_blanket_retrieval_improvement_claim_pattern_fires() -> None:
    """The pattern above actually catches the exact wording this pass
    found and corrected in six files.
    """
    broken = (
        "fixing the diagnosed cause moved every retrieval metric by "
        "7.6x to 13.5x (hit rate@100 0.0044 -> 0.0336)"
    )
    assert BLANKET_RETRIEVAL_IMPROVEMENT_CLAIM.search(broken)

    fixed = (
        "fixing the diagnosed cause improved the four relevance metrics "
        "by 7.6x-13.5x; catalog coverage improved separately, by 1.5x"
    )
    assert not BLANKET_RETRIEVAL_IMPROVEMENT_CLAIM.search(fixed)
