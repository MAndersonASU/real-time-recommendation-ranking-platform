from recommender.evaluation.evaluate_explanations import _independently_verify_faithfulness

TEMPLATE_CATEGORY_MATCH = "Recommended because it matches your interest in sports."
TEMPLATE_CONTENT_ONLY = "Recommended because its content resembles articles you've read before."


def test_verify_faithfulness_passes_when_category_word_is_present():
    assert _independently_verify_faithfulness(
        TEMPLATE_CATEGORY_MATCH, "sports", category_match=True, template=TEMPLATE_CATEGORY_MATCH
    )


def test_verify_faithfulness_fails_when_category_word_is_missing():
    assert not _independently_verify_faithfulness(
        "It is a good choice for you.", "sports", category_match=True, template=TEMPLATE_CATEGORY_MATCH
    )


def test_verify_faithfulness_is_case_insensitive():
    assert _independently_verify_faithfulness(
        "This matches your interest in SPORTS.",
        "sports",
        category_match=True,
        template=TEMPLATE_CATEGORY_MATCH,
    )


def test_verify_faithfulness_ignores_category_when_match_is_false():
    # No category-match claim was made, so nothing about the category
    # word needs to appear for the explanation to be faithful.
    assert _independently_verify_faithfulness(
        TEMPLATE_CONTENT_ONLY, "sports", category_match=False, template=TEMPLATE_CONTENT_ONLY
    )


def test_verify_faithfulness_rejects_a_fabricated_claim_on_content_only_evidence():
    """Regression test for a real bug: this "independent" verification
    shared the exact same blind spot as the generation module's own
    gate -- it only ever checked the category-match branch, so a
    fabricated claim on content-only evidence (no category to check)
    was counted as faithful. This is the real fabrication the audit
    reproduced. Fails on the pre-fix function (returns True) and passes
    once it also rejects an invented capitalized term.
    """
    fabricated = "The President personally selected this story for you."

    assert not _independently_verify_faithfulness(
        fabricated, "sports", category_match=False, template=TEMPLATE_CONTENT_ONLY
    )


def test_verify_faithfulness_rejects_an_invented_entity_even_with_the_category_word_present():
    fabricated_but_keeps_category = "NASA recommends this because you like sports."

    assert not _independently_verify_faithfulness(
        fabricated_but_keeps_category,
        "sports",
        category_match=True,
        template=TEMPLATE_CATEGORY_MATCH,
    )
