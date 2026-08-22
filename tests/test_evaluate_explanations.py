from recommender.evaluation.evaluate_explanations import _independently_verify_faithfulness


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
