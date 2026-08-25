from unittest.mock import MagicMock, patch

from recommender.explanation.generation import (
    APPROVED_TEMPLATES,
    MIN_CONTENT_SIMILARITY_FOR_GROUNDING,
    MODEL_NAME,
    MODEL_REVISION,
    _preserves_required_facts,
    build_template_explanation,
    extract_facts,
    generate_explanation,
    has_sufficient_evidence,
    load_generator,
    select_template_key,
)
from recommender.explanation.retrieval import SupportContext


def test_load_generator_pins_the_model_revision():
    """Regression test for a real bug, found by audit: from_pretrained
    was called with no `revision` at all, so it resolved to whatever
    "main" pointed to on the Hub at download time -- a later push to
    that repo would silently change which weights get loaded, with no
    way to detect it happened. Fails on the pre-fix code (no `revision`
    kwarg reaches either call) and passes once both are pinned. Mocked,
    not a real download, so this stays fast and doesn't need network
    access.
    """
    load_generator.cache_clear()
    fake_tokenizer_cls = MagicMock()
    fake_model_cls = MagicMock()
    fake_model_cls.from_pretrained.return_value.eval.return_value = fake_model_cls.from_pretrained.return_value

    with patch.dict(
        "sys.modules",
        {"transformers": MagicMock(T5Tokenizer=fake_tokenizer_cls, T5ForConditionalGeneration=fake_model_cls)},
    ):
        load_generator()

    fake_tokenizer_cls.from_pretrained.assert_called_once_with(MODEL_NAME, revision=MODEL_REVISION)
    fake_model_cls.from_pretrained.assert_called_once_with(MODEL_NAME, revision=MODEL_REVISION)
    load_generator.cache_clear()


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
    generator = _FakeGenerator("This is recommended because it matches your interest in sports.")

    # Opt-in: the rewrite path is no longer the default (see
    # generate_explanation's docstring on why the deterministic template
    # states the factual relationship).
    response = generate_explanation(context, generator=generator, allow_generative_rewrite=True)

    assert response.refused is False
    assert response.explanation == "This is recommended because it matches your interest in sports."
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


def test_generate_explanation_rejects_a_lowercase_fabricated_attribution():
    """Regression test for a real gap: the original gate only ever
    flagged an *unfamiliar capitalized* word, so a fully lowercase
    fabrication passed unchanged. This is one of the exact examples
    confirmed to have been accepted before this fix.
    """
    context = _context(category_match=False, content_similarity=0.4)
    generator = _FakeGenerator("the president personally selected this story for you.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == build_template_explanation(context)
    assert "president" not in response.explanation.lower()


def test_generate_explanation_rejects_a_lowercase_fabricated_causation_claim():
    """A second exact example confirmed to have been accepted before
    this fix -- a fabricated causal claim with no capitalized word at
    all.
    """
    context = _context(category_match=False, content_similarity=0.4)
    generator = _FakeGenerator("this was selected because your employer requested it.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == build_template_explanation(context)
    assert "employer" not in response.explanation.lower()


def test_generate_explanation_rejects_a_fabrication_that_keeps_the_real_category_word():
    """The third exact example confirmed to have been accepted before
    this fix: the fabrication is mixed-case and *does* keep the real
    category word ("Sports"), so a check that only verified the category
    word was present (without also checking for unsupported content)
    would have wrongly accepted it.
    """
    context = _context(category_match=True, content_similarity=0.0, category="sports")
    generator = _FakeGenerator("Sports officials confirmed this guarantees financial success.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == build_template_explanation(context)
    assert "guarantees" not in response.explanation.lower()
    assert "financial" not in response.explanation.lower()


def test_generate_explanation_rejects_a_sentence_initial_fabricated_entity():
    context = _context(category_match=True, content_similarity=0.0, category="sports")
    generator = _FakeGenerator("President Smith recommends this because it matches your interest in sports.")

    response = generate_explanation(context, generator=generator)

    assert response.explanation == build_template_explanation(context)
    assert "smith" not in response.explanation.lower()


def test_generate_explanation_accepts_a_genuine_rewrite_with_no_invented_terms():
    """Confirms the closed-vocabulary check doesn't overreach: a rewrite
    built only from the template's own words plus pure grammatical
    scaffolding must still be accepted -- the fix should reject
    fabrication, not reject every rewrite.
    """
    context = _context(category_match=False, content_similarity=0.4)
    generator = _FakeGenerator(
        "It is recommended because its content closely resembles articles you have read before."
    )

    response = generate_explanation(context, generator=generator, allow_generative_rewrite=True)

    assert response.explanation == (
        "It is recommended because its content closely resembles articles you have read before."
    )


# --- Constrained deterministic design -------------------------------


def test_explanation_is_deterministic_and_never_calls_a_model_by_default():
    """The factual relationship is stated by an approved template, not
    by a model. A generator supplied but not opted into must never be
    invoked.
    """
    class _ExplodingGenerator:
        def generate(self, prompt):
            raise AssertionError("no model may be called on the default path")

    context = _context(category_match=True, content_similarity=0.4, category="sports")

    response = generate_explanation(context, generator=_ExplodingGenerator())

    assert response.explanation == build_template_explanation(context)
    assert "sports" in response.explanation


def test_every_produced_sentence_comes_from_the_approved_template_set():
    """Whatever combination of evidence holds, the output is one of the
    approved sentences with only the category substituted.
    """
    for category_match, similarity in ((True, 0.4), (True, 0.0), (False, 0.4)):
        context = _context(
            category_match=category_match, content_similarity=similarity, category="sports"
        )
        rendered = build_template_explanation(context)
        key = select_template_key(extract_facts(context))
        assert rendered == APPROVED_TEMPLATES[key].format(category="sports")


def test_an_implausible_category_value_is_never_substituted_into_output():
    """The single placeholder is filled only from a validated value, so
    a corrupted category cannot reach the user through it.
    """
    context = _context(
        category_match=True, content_similarity=0.4,
        category="<script>alert(1)</script>",
    )

    rendered = build_template_explanation(context)

    assert "<script>" not in rendered
    assert rendered == APPROVED_TEMPLATES[("content",)]


# --- Adversarial: why the lexical gate is not a semantic one ---------
#
# Each case below is built ONLY from words the gate already permits, so
# it passes the lexical check while meaning something the evidence does
# not support. These are not hypothetical -- they are the reason
# generation is opt-in and the deterministic template is authoritative.


def _lexically_passes(text, context):
    template = build_template_explanation(context)
    return _preserves_required_facts(text, context, template)


def test_lexical_gate_accepts_reordered_words_that_change_the_claim():
    context = _context(category_match=True, content_similarity=0.4, category="sports")

    # Every word here appears in the template or the scaffolding set,
    # but the sentence now asserts the reader's articles resemble the
    # content, reversing which thing is being compared to which.
    reordered = (
        "Articles you've read before closely resembles its content and your interest "
        "in sports matches it."
    )

    assert _lexically_passes(reordered, context), (
        "this case exists to document that the lexical gate passes it"
    )


def test_lexical_gate_accepts_a_reversed_subject_object_relationship():
    context = _context(category_match=True, content_similarity=0.0, category="sports")

    reversed_claim = "Your interest in sports is recommended because it matches this."

    assert _lexically_passes(reversed_claim, context)


def test_lexical_gate_accepts_an_unsupported_claim_built_from_allowed_words():
    context = _context(category_match=True, content_similarity=0.0, category="sports")

    # Every word is already available to the gate, yet the sentence
    # asserts something the evidence never established: that the reader
    # is *in* sports, rather than interested in the category.
    unsupported = "It matches your interest because you are in sports."

    assert _lexically_passes(unsupported, context)


def test_lexical_gate_accepts_a_fabricated_actor_made_only_of_allowed_words():
    context = _context(category_match=True, content_similarity=0.4, category="sports")

    # "we" is grammatical scaffolding; the sentence still invents an
    # actor and a motive the system never had.
    fabricated_actor = "We matches your interest in sports because we have your content."

    assert _lexically_passes(fabricated_actor, context)


def test_the_deterministic_path_is_immune_to_all_of_the_above():
    """The point of the adversarial cases: none of them can occur when
    no model is asked to state the relationship in the first place.
    """
    context = _context(category_match=True, content_similarity=0.4, category="sports")

    response = generate_explanation(context)

    assert response.explanation == APPROVED_TEMPLATES[("category", "content")].format(
        category="sports"
    )
