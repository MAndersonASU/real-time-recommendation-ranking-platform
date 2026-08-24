from recommender.evaluation.evaluate_explanations import (
    _contains_a_known_fabrication_indicator,
    _independently_verify_faithfulness,
)


def test_verify_faithfulness_passes_when_category_word_is_present():
    assert _independently_verify_faithfulness(
        "Recommended because it matches your interest in sports.", "sports", category_match=True
    )


def test_verify_faithfulness_fails_when_category_word_is_missing():
    assert not _independently_verify_faithfulness(
        "It is a good choice for you.", "sports", category_match=True
    )


def test_verify_faithfulness_is_case_insensitive():
    assert _independently_verify_faithfulness(
        "This matches your interest in SPORTS.", "sports", category_match=True
    )


def test_verify_faithfulness_ignores_category_when_match_is_false():
    # No category-match claim was made, so nothing about the category
    # word needs to appear for the explanation to be faithful.
    assert _independently_verify_faithfulness(
        "Recommended because its content resembles articles you've read before.",
        "sports",
        category_match=False,
    )


def test_verify_faithfulness_rejects_a_lowercase_fabricated_attribution():
    """Regression test for one of the exact fabrications confirmed to
    have been accepted by both the generation module's own gate *and*
    this "independent" check before this fix -- a fully lowercase
    fabrication, so a capitalization-based check (what both used to be)
    never had a chance to catch it.
    """
    fabricated = "the president personally selected this story for you."

    assert not _independently_verify_faithfulness(fabricated, "sports", category_match=False)


def test_verify_faithfulness_rejects_a_lowercase_fabricated_causation_claim():
    fabricated = "this was selected because your employer requested it."

    assert not _independently_verify_faithfulness(fabricated, "sports", category_match=False)


def test_verify_faithfulness_rejects_a_fabrication_that_keeps_the_real_category_word():
    """The third exact example: mixed-case, and it *does* keep the
    real category word -- a check that only verified the category word
    was present would have wrongly accepted this.
    """
    fabricated = "Sports officials confirmed this guarantees financial success."

    assert not _independently_verify_faithfulness(fabricated, "sports", category_match=True)


def test_verify_faithfulness_rejects_an_invented_entity_even_with_the_category_word_present():
    fabricated_but_keeps_category = "NASA recommends this because you like sports."

    assert not _independently_verify_faithfulness(
        fabricated_but_keeps_category, "sports", category_match=True
    )


def test_contains_a_known_fabrication_indicator_is_true_for_each_blacklisted_category():
    assert _contains_a_known_fabrication_indicator("the president selected this for you")
    assert _contains_a_known_fabrication_indicator("this guarantees financial success")
    assert _contains_a_known_fabrication_indicator("officials confirmed this personally")


def test_contains_a_known_fabrication_indicator_is_false_for_real_template_wording():
    assert not _contains_a_known_fabrication_indicator(
        "Recommended because it matches your interest in sports and its content "
        "closely resembles articles you've read before."
    )
