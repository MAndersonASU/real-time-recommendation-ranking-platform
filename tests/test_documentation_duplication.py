"""Guards against wording duplicated by bulk editorial changes.

A search-and-replace across the documentation set can substitute a
component name into a sentence that already names that component,
producing "the retrieval model's two-tower retrieval model" or "(the
ranking model, the ranking model)". The result is grammatical enough to
survive proofreading and invisible to a plain duplicate-word check.

Three detectors run over rendered prose:

1. ``duplicate_words``     - the same word twice in a row ("the the").
2. ``duplicated_phrases``  - a 2-4 word phrase naming a component,
                             repeated immediately after itself.
3. ``component_echo``      - a component noun repeated within three
                             words, with no coordination between the two
                             occurrences.

Legitimate repetition is overwhelmingly coordination ("streaming replay
and replay evaluation", "the two-tower model, the ranking model, the
index"), so a conjunction or comma between two occurrences clears them.
Anything else needs an entry in ``ACCEPTED_REPETITION`` with a reason.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tests.test_documentation import MARKDOWN, md_id

# Tokens: words (keeping hyphen/slash/apostrophe compounds whole) and
# numbers. Numbers are tokenised so that stripping them cannot make two
# distant words look adjacent.
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:[-/'\u2019][A-Za-z0-9_]+)*|\d[\d.,:%-]*")

# Repetition either side of one of these reads as a list or a contrast,
# not as a bulk-edit artefact.
COORDINATION = frozenset(
    {"and", "or", "nor", "but", "then", "versus", "vs", "also", "plus", "xcomma"}
)

# Nouns the terminology rewrite substituted. Echoes of these are what the
# rewrite could plausibly have introduced.
COMPONENTS = frozenset({
    "retrieval", "ranking", "reranking", "streaming", "replay", "evaluation",
    "baseline", "baselines", "explanation", "serving", "ablation", "ablations",
    "pipeline", "model", "models", "index", "catalog", "slate",
})

# Placeholders standing in for elided spans, so removing a span never
# makes its neighbours adjacent. Compared after normalisation, so they
# are held lowercase here. Never reported.
PLACEHOLDERS = frozenset({"xref", "xcomma"})

ECHO_WINDOW = 3  # words; every observed artefact repeated within three

# Narrow, individually justified exceptions. Each entry is an exact
# normalised fragment, not a pattern or a whole-file exemption.
ACCEPTED_REPETITION: dict[str, str] = {}


def rendered_prose(text: str) -> str:
    """Markdown reduced to prose, with elided spans left as placeholders.

    Order matters: fenced blocks and table rows go before inline-code
    removal, because an unbalanced backtick inside a table would
    otherwise swallow the row separators and join unrelated cells.
    """
    text = re.sub(r"```.*?```", " XREF ", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    kept = [
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("|")  # tables repeat by design
    ]
    text = "\n".join(kept)
    # Join wrapped lines inside a paragraph before removing inline code:
    # a span like `log_run(run_name,` is routinely wrapped mid-span, and
    # a line-bounded pattern would leave half of it in the prose.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"`[^`\n]*`", " XREF ", text)
    text = re.sub(r"\]\([^)]*\)", "] XREF ", text)
    text = re.sub(r"https?://\S+", " XREF ", text)
    return text.replace(",", " XCOMMA ")


def _normalise(word: str) -> str:
    """Lowercase, and drop a possessive so ``model's`` matches ``model``."""
    return re.sub(r"['\u2019]s$", "", word.lower())


def _sentences(paragraph: str) -> list[list[str]]:
    flat = " ".join(paragraph.split())
    return [
        [_normalise(m.group(0)) for m in TOKEN.finditer(sentence)]
        for sentence in re.split(r"(?<=[.:;!?])\s+", flat)
    ]


def _fragment(words: list[str], start: int, stop: int) -> str:
    span = words[max(0, start - 2):stop + 2]
    return " ".join(w for w in span if w not in PLACEHOLDERS)


def duplicate_words(words: list[str]) -> list[str]:
    """The same word twice in a row."""
    out = []
    for i in range(len(words) - 1):
        word = words[i]
        if word != words[i + 1] or word in PLACEHOLDERS:
            continue
        if len(word) < 2 or word[0].isdigit():
            continue  # units and figures repeat legitimately in tallies
        out.append(_fragment(words, i, i + 1))
    return out


def duplicated_phrases(words: list[str]) -> list[str]:
    """A 2-4 word phrase naming a component, repeated right after itself.

    Placeholders are dropped first so that "the ranking model, the
    ranking model" is seen as an immediate repeat, while a genuine list
    ("the two-tower model, the ranking model, the index") is not, because
    its consecutive phrases differ.
    """
    content = [w for w in words if w not in PLACEHOLDERS]
    out = []
    for size in (2, 3, 4):
        for i in range(len(content) - size * 2 + 1):
            phrase = content[i:i + size]
            if not COMPONENTS & set(phrase):
                continue
            if content[i + size:i + size * 2] == phrase:
                out.append(" ".join(content[i:i + size * 2]))
    return out


def component_echo(words: list[str]) -> list[str]:
    """A component noun repeated within ECHO_WINDOW, uncoordinated."""
    out = []
    for i, word in enumerate(words):
        if word not in COMPONENTS:
            continue
        for j in range(i + 1, min(i + 1 + ECHO_WINDOW, len(words))):
            if words[j] != word:
                continue
            if COORDINATION & set(words[i + 1:j]):
                break  # a list or a contrast, not an artefact
            out.append(_fragment(words, i, j))
            break
    return out



# Substituting a multi-word component name for a single word can leave a
# determiner stranded in front of the article that came with the
# replacement ("from every the preceding work"). No English sentence
# needs these pairs, and each is listed rather than matched by class.
STRANDED_DETERMINERS = frozenset({
    ("every", "the"), ("every", "a"), ("every", "an"),
    ("each", "the"), ("each", "a"), ("each", "an"),
    ("the", "a"), ("the", "an"), ("a", "the"), ("an", "the"),
})


def stranded_determiners(words: list[str]) -> list[str]:
    """A determiner left in front of an article by a substitution."""
    return [
        _fragment(words, i, i + 1)
        for i in range(len(words) - 1)
        if (words[i], words[i + 1]) in STRANDED_DETERMINERS
    ]

DETECTORS = (
    duplicate_words,
    duplicated_phrases,
    component_echo,
    stranded_determiners,
)


def findings(markdown: str) -> list[str]:
    """Every duplication finding in one Markdown document."""
    out = []
    for paragraph in re.split(r"\n\s*\n", rendered_prose(markdown)):
        for words in _sentences(paragraph):
            for detector in DETECTORS:
                for hit in detector(words):
                    if hit not in ACCEPTED_REPETITION:
                        out.append(hit)
    return out


@pytest.mark.parametrize("path", MARKDOWN, ids=md_id)
def test_no_duplicated_wording(path: pathlib.Path) -> None:
    """No document repeats a word, phrase or component name by accident."""
    hits = findings(path.read_text(encoding="utf-8"))
    assert not hits, f"{md_id(path)}: " + "; ".join(sorted(set(hits)))


# Every sentence a bulk terminology rewrite actually broke in this
# repository, paired with the wording that replaced it. The left column
# must be rejected and the right column accepted, so the detectors above
# cannot be loosened without a fixture turning red.
REGRESSIONS: tuple[tuple[str, str], ...] = (
    (
        (
            "asks about *learned embeddings* (the retrieval model's"
            " two-tower retrieval model), and"
        ),
        'asks about *learned embeddings* (the two-tower retrieval model), and',
    ),
    (
        (
            'Candidate retrieval (the retrieval model) and coverage metrics'
            ' need to account for a'
        ),
        'Candidate retrieval and coverage metrics need to account for a',
    ),
    (
        (
            "the preceding work — the baselines' three baselines, the"
            " retrieval model's retrieval evaluation, the ranking comparison"
        ),
        (
            'the preceding work — the three baselines, the retrieval'
            ' evaluation, the ranking comparison'
        ),
    ),
    (
        '`backfill.py` reads the report files from every the preceding work',
        '`backfill.py` reads the report files from all the preceding work',
    ),
    (
        (
            'running the streaming replay (the streaming pipeline) against'
            ' a matching population'
        ),
        'running the streaming pipeline against a matching population',
    ),
    (
        'relevant is this item" (the ranking model, the ranking model) from',
        'relevant is this item" (the ranking model) from',
    ),
    (
        (
            'Doing so would mean the streaming pipeline\'s "streaming'
            ' replay" secretly re-processes'
        ),
        'Doing so would mean the streaming replay secretly re-processes',
    ),
    (
        "and replay evaluation's evaluation would no longer be measuring",
        'and replay evaluation would no longer be measuring',
    ),
    (
        '`recommend_recent_cache_total{result}` from the the preceding work.',
        '`recommend_recent_cache_total{result}` from the preceding work.',
    ),
    (
        (
            'The optional explanation generation generative/RAG explanation'
            ' layer explains an already-selected recommendation'
        ),
        (
            'The optional generative/RAG explanation layer explains an'
            ' already-selected recommendation'
        ),
    ),
    (
        (
            'a second, stronger rung on the same ladder — the retrieval'
            " model's embedding model now has to beat this"
        ),
        (
            'a second, stronger rung on the same ladder — the embedding'
            ' model now has to beat this'
        ),
    ),
    (
        'Any later model (the retrieval model onward) that improves hit rate',
        (
            'Any later model (from the retrieval model onward) that'
            ' improves hit rate'
        ),
    ),
    (
        (
            "Locked 2026-08-18, after the baselines' three baselines"
            ' already had results measured under it.'
        ),
        (
            'Locked 2026-08-18, after the three baselines already had'
            ' results measured under it.'
        ),
    ),
    (
        "it's the profiling result from the the preceding work, now confirmed",
        "it's the profiling result from the preceding work, now confirmed",
    ),
    (
        (
            "the same frozen candidate-set definition the baselines'"
            ' baselines used'
        ),
        'the same frozen candidate-set definition the baselines used',
    ),
    (
        (
            "the retrieval model's first learned model. Architecture and"
            ' training only'
        ),
        "The project's first learned model. Architecture and training only",
    ),
    (
        'Synthesizes what every the preceding work already measured',
        'Synthesizes what all the preceding work already measured',
    ),
    (
        (
            'This check defines the message format every the streaming'
            ' components shares.'
        ),
        (
            'This check defines the message format all the streaming'
            ' components shares.'
        ),
    ),
)


@pytest.mark.parametrize(
    "broken", [b for b, _ in REGRESSIONS], ids=range(len(REGRESSIONS))
)
def test_known_broken_wording_is_rejected(broken: str) -> None:
    """Each sentence a bulk rewrite broke is still detected."""
    assert findings(broken), f"no longer detected: {broken!r}"


@pytest.mark.parametrize(
    "repaired", [r for _, r in REGRESSIONS], ids=range(len(REGRESSIONS))
)
def test_repaired_wording_is_accepted(repaired: str) -> None:
    """The wording that replaced it reads clean."""
    assert not findings(repaired), f"false positive: {repaired!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        # Coordination: two genuinely different activities.
        "used for streaming replay and replay evaluation; no longer untouched",
        # A list of distinct artifacts.
        "loads: the two-tower model, the ranking model, the exact index.",
        # Distant, deliberate re-use of a noun across a clause boundary.
        "a real explanation per item — the optional explanation layer",
        # Contrast rather than duplication.
        "the ranking model and the retrieval model disagree",
    ],
)
def test_legitimate_repetition_is_not_flagged(phrase: str) -> None:
    """Coordination and lists repeat component names on purpose."""
    assert not findings(phrase), f"false positive: {phrase!r}"
