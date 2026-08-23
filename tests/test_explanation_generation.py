from recommender.explanation.generation import (
    MIN_CONTENT_SIMILARITY_FOR_GROUNDING,
    build_template_explanation,
    generate_explanation,
    has_sufficient_evidence,
)
from recommender.explanation.retrieval import SupportContext


class _FakeGenerator:
    """A small, deterministic stand-in -- exercises the real wiring
    (template building, the faithfulness gate, fallback) without
    downloading or running the real model, the same synthetic-in-CI
    pattern already used for Kafka/Redis and the licensed MIND dataset.
    """

    def __init__(self, response: str):
        self.response = response
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


def _context(**overrides) -> SupportContext:
    defaults = {
        "news_id": "n1",
        "title": "team wins big game",
        "category": "sports",
        "subcategory": "football",
        "abstract": "a real recap of the match",
        "category_match": False,
        "content_similarity": 0.0,
        "retrieval_score": 0.2,
        "user_history_length": 5,
    }
    defaults.update(overrides)
    return SupportContext(**defaults)


def test_has_sufficient_evidence_true_on_category_match_alone():
    context = _context(category_match=True, content_similarity=0.0)

    assert has_sufficient_evidence(context) is True


def test_has_sufficient_evidence_true_on_content_similarity_alone():
    context = _context(category_match=False, content_similarity=MIN_CONTENT_SIMILARITY_FOR_GROUNDING)

    assert has_sufficient_evidence(context) is True


def test_has_sufficient_evidence_false_when_neither_signal_is_present():
    context = _context(category_match=False, content_similarity=0.0)

    assert has_sufficient_evidence(context) is False


def test_generate_explanation_refuses_without_calling_the_generator():
    context = _context(category_match=False, content_similarity=0.0)
    generator = _FakeGenerator("this should never be returned")

    response = generate_explanation(context, generator=generator)

    assert response.refused is True
    assert response.explanation == ""
    assert response.evidence_used == []
    assert generator.last_prompt is None


def test_generate_explanation_uses_the_models_rewrite_when_it_keeps_the_real_category():
    context = _context(category_match=True, content_similarity=0.0, category="sports")
    generator = _FakeGenerator("This was picked for you because you like sports.")

    response = generate_explanation(context, generator=generator)

    assert response.refused is False
    assert response.explanation == "This was picked for you because you like sports."
    assert response.evidence_used == ["category_match"]


def test_generate_explanation_falls_back_to_the_template_when_the_rewrite_drops_the_category():
    context = _context(category_match=True, content_similarity=0.0, category="lifestyle")
    generator = _FakeGenerator("It is a good choice for you.")  # real observed model behavior

    response = generate_explanation(context, generator=generator)

    assert response.refused is False
    assert response.explanation == build_template_explanation(context)
    assert "lifestyle" in response.explanation


def test_generate_explanation_reports_both_evidence_types_when_both_apply():
    context = _context(category_match=True, content_similarity=0.4)
    generator = _FakeGenerator("some explanation about sports and history")

    response = generate_explanation(context, generator=generator)

    assert response.evidence_used == ["category_match", "content_similarity"]


def test_build_template_explanation_names_the_real_category():
    context = _context(category_match=True, content_similarity=0.0, category="autos")

    template = build_template_explanation(context)

    assert "autos" in template


def test_build_template_explanation_combines_both_clauses_when_both_apply():
    context = _context(category_match=True, content_similarity=0.4, category="autos")

    template = build_template_explanation(context)

    assert "autos" in template
    assert "read before" in template


def test_generate_explanation_rejects_a_fabricated_claim_on_content_only_evidence():
    """Regression test for a real, reproduced bug: the faithfulness gate
    only ever checked the category-match branch, so a recommendation
    grounded purely in content similarity (no category to check) had no
    real check at all -- any fabricated text passed unchanged. This is
    the exact fabrication real testing produced: a claim about a named
    real-world figure with zero connection to any real matched signal.
    Fails on the pre-fix gate (the fabrication is returned as-is) and
    passes once the gate also rejects an invented capitalized term.
    """
    context = _context(category_match=False, content_similarity=0.4)
    generator = _FakeGenerator("The President personally selected this story for you.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == build_template_explanation(context)
    assert "President" not in response.explanation


def test_generate_explanation_rejects_an_invented_entity_even_when_the_category_word_is_kept():
    """The category-word check alone isn't enough: a rewrite could keep
    the required category word and still invent an unrelated claim
    alongside it. The capitalized-term check catches this even when the
    category-specific check alone would have passed it.
    """
    context = _context(category_match=True, content_similarity=0.0, category="sports")
    generator = _FakeGenerator("NASA recommends this because you like sports.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == build_template_explanation(context)
    assert "NASA" not in response.explanation


def test_generate_explanation_accepts_a_genuine_rewrite_with_no_invented_terms():
    """Confirms the new check doesn't overreach: an honest rewrite that
    only rewords the template, introducing no new capitalized term,
    must still be accepted -- the fix should reject fabrication, not
    reject every rewrite.
    """
    context = _context(category_match=False, content_similarity=0.4)
    generator = _FakeGenerator("this was picked because its content closely matches what you read.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == "this was picked because its content closely matches what you read."
