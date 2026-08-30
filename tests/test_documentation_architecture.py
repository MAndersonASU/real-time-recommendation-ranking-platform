"""Explicit assertions that specific current-architecture claims hold.

The guards elsewhere in this suite catch staleness by pattern --
duplicated wording, a table cell that disagrees with its report, a
count that no longer matches. None of them would catch a document
being edited back to a *specific*, previously-corrected wrong claim
that happens not to collide with any of those patterns. This module
pins four such claims directly: each is a fact this pass corrected
after finding it wrong, named explicitly so a future edit that
reintroduces the old, false version fails here even if it does not
trip any pattern-based guard.
"""

from __future__ import annotations

import json

from tests.test_documentation import DOCS, REPORTS


def _doc(name: str) -> str:
    matches = sorted(DOCS.rglob(name))
    assert matches, f"{name} not found under docs/"
    return matches[0].read_text(encoding="utf-8")


def _report(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def test_event_ids_are_documented_as_deterministic() -> None:
    """Replay ids must be documented as stable, not random.

    `stable_event_id` (`src/recommender/streaming/schema.py`) derives
    `event_id` from an event's own immutable fields via `uuid5` by
    default, specifically so a replayed event is recognised as a
    duplicate rather than looking like new traffic. event-schema.md
    once said the opposite -- "two events built from identical inputs
    still get distinct event ids" -- which contradicts the very
    duplicate-detection mechanism this schema exists to support.
    """
    text = _doc("event-schema.md")
    assert "identical inputs produce the identical id" in text, (
        "event-schema.md no longer documents make_event's default id as "
        "deterministic"
    )
    assert "distinct event ids" not in text, (
        "event-schema.md has reintroduced the false claim that identical "
        "inputs get distinct event ids"
    )


def test_duplicate_event_returns_current_not_historical_state() -> None:
    """A duplicate event must be documented as returning current state.

    `claim_and_apply_event`'s Lua script (`src/recommender/features/
    state_store.py`) returns the state key's current contents on a
    duplicate. An earlier version of streaming-consumer.md described a
    different, superseded design that stored state inside the claim key
    and *restored* that historical, original-event state on a
    duplicate -- rolling the user back to whenever that event first
    landed and discarding everything applied since. The document now
    narrates that earlier design as history (accurately labelled as
    superseded), which this check leaves alone; what it pins is that the
    *current*-behaviour claim is still present and correct.
    """
    text = _doc("streaming-consumer.md")
    assert "returns the current state" in text, (
        "streaming-consumer.md no longer states that a duplicate event "
        "returns current state"
    )
    assert "An earlier fix stored the resulting state" in text, (
        "streaming-consumer.md no longer labels the old claim-carried-state "
        "design as superseded history -- check it has not been restated as "
        "current behaviour"
    )


def test_ranking_model_is_documented_as_five_inputs_not_six() -> None:
    """The ranking model's input count must read five, not six.

    Six features are computed and persisted (`docs/experiments/
    ranking-features.md`); `popularity` is deliberately excluded from
    the trained model's own inputs (`docs/experiments/ranking-model.md`,
    which found it degrades validation AUC below chance). A document
    describing "the six features" as what the model uses conflates the
    two counts.
    """
    features_doc = _doc("ranking-features.md")
    assert "model actually uses five of them" in features_doc, (
        "ranking-features.md no longer distinguishes six computed features "
        "from the five the trained model uses"
    )
    assert "## The six features" not in features_doc, (
        "ranking-features.md's heading has reverted to naming six features "
        "without distinguishing computed from used"
    )

    model_doc = _doc("ranking-model.md")
    assert "five\nused by the trained model" in model_doc, (
        "ranking-model.md's opening no longer states five features are "
        "used by the trained model"
    )


def test_current_latency_leader_matches_the_published_report() -> None:
    """serving-latency.md's claimed dominant stage must match the report.

    The pipeline changed twice since the 2026-08-21 measurement: retrieval
    depth was raised and a cold-start popularity path was added
    (2026-08-24), making candidate retrieval the largest stage; then
    SERVING-DURABLE-HISTORY-69's fix (2026-08-30) meant far fewer
    requests hit that expensive popularity path at all, and reranking
    became the largest stage again -- for a different reason than the
    2026-08-21 measurement's own reranking-dominant result, which
    predates the retrieval-depth change entirely. This ties the
    document's own prose claim to the actual numbers in the committed
    report, so if a future rebuild changes which stage dominates, this
    fails instead of silently going stale the way the original table
    did.
    """
    report = _report("serving-latency.json")
    stages = report["results"]["by_stage"]
    largest = max(stages, key=lambda name: stages[name]["p50_ms"])
    assert largest == "reranking_ms", (
        f"serving-latency.json now reports {largest!r} as the largest stage, "
        "not reranking_ms -- update serving-latency.md's current-measurement "
        "section and its dependent figures in conclusions.md, ablations.md "
        "and demonstration-guide.md to match"
    )

    text = _doc("serving-latency.md")
    assert "is now the largest stage" in text, (
        "serving-latency.md no longer names reranking as the largest stage, "
        "but the report still says it is -- documentation has drifted from "
        "the report"
    )
