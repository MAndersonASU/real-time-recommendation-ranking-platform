"""User ids must be rejected for what they contain, not what they look like.

The original defect: validation excluded ASCII control characters, which
reads as thorough and is not. Unicode carries a whole class of
non-printing format characters that survive that check -- a zero-width
space, a bidirectional mark, a byte-order mark. Each is invisible in a
log line, in a terminal, and in a rendered page, so `U123<ZWSP>` and
`U123` look identical to every human reading them while being different
dictionary keys, different Redis keys, and different cache entries.

Measured against the old rule, all fifteen code points below would have
been accepted.

The fix was a positive allow-list. These tests are the regression
coverage the audit noted was still missing: the behaviour was correct but
nothing pinned it, so a later "let's be more permissive" change could
undo it silently.
"""

import re

import pytest
from pydantic import ValidationError

from recommender.serving.contract import (
    MAX_USER_ID_LENGTH,
    USER_ID_PATTERN,
    RecommendationRequest,
)

# Code points as integers, resolved with chr() at import time. Neither
# raw characters nor backslash escapes: raw characters make this source
# unreadable (the exact problem under test) and Ruff rejects them
# (PLE2502/PLE2515), while escapes are silently converted back to raw
# characters by several tools that rewrite Python source. An integer
# survives every round trip, and the name beside it is what makes the
# table reviewable.
INVISIBLE_CODE_POINTS = {
    "zero-width space": 0x200B,
    "zero-width non-joiner": 0x200C,
    "zero-width joiner": 0x200D,
    "byte-order mark": 0xFEFF,
    "left-to-right mark": 0x200E,
    "right-to-left mark": 0x200F,
    "left-to-right override": 0x202D,
    "right-to-left override": 0x202E,
    "word joiner": 0x2060,
    "soft hyphen": 0x00AD,
    "no-break space": 0x00A0,
    "ideographic space": 0x3000,
    "line separator": 0x2028,
    "paragraph separator": 0x2029,
    "next line": 0x0085,
}

INVISIBLE_CHARACTERS = {name: chr(cp) for name, cp in INVISIBLE_CODE_POINTS.items()}


@pytest.mark.parametrize("name,character", sorted(INVISIBLE_CHARACTERS.items()))
def test_invisible_characters_are_rejected(name, character):
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id=f"U123{character}", num_candidates=5)


@pytest.mark.parametrize("name,character", sorted(INVISIBLE_CHARACTERS.items()))
def test_invisible_characters_are_rejected_anywhere_in_the_id(name, character):
    """Leading and interior positions too -- a trailing-only check would
    pass the parametrised test above while leaving the hole open.
    """
    for candidate in (f"{character}U123", f"U1{character}23"):
        with pytest.raises(ValidationError):
            RecommendationRequest(user_id=candidate, num_candidates=5)


def test_a_bidi_override_cannot_disguise_an_id():
    """U+202E renders the following text right-to-left, so a log reader
    sees something other than the key actually used.
    """
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id=f"U{chr(0x202E)}321", num_candidates=5)


@pytest.mark.parametrize(
    "candidate",
    [
        "U123" + chr(0x0301),  # combining acute accent
        chr(0x0430) + "U123",  # Cyrillic a, visually identical to Latin a
        "U" + chr(0xFF11) + chr(0xFF12) + chr(0xFF13),  # fullwidth digits
        "U123\U0001f600",  # emoji
        "U123\t",
        "U123\n",
        "U 123",
        "U123/../etc",
        "U123%00",
        "",
    ],
)
def test_other_unsafe_identifiers_are_rejected(candidate):
    with pytest.raises(ValidationError):
        RecommendationRequest(user_id=candidate, num_candidates=5)


@pytest.mark.parametrize("candidate", ["U123", "u-123", "U_123", "U.123", "U:123", "U123-abc.d"])
def test_ordinary_identifiers_are_still_accepted(candidate):
    """The allow-list has to admit real ids, or it is just an outage.
    MIND's own ids look like `U123`.
    """
    assert RecommendationRequest(user_id=candidate, num_candidates=5).user_id == candidate


def test_the_length_bound_is_enforced_at_the_boundary():
    longest = "U" * MAX_USER_ID_LENGTH
    assert RecommendationRequest(user_id=longest, num_candidates=5).user_id == longest

    with pytest.raises(ValidationError):
        RecommendationRequest(user_id="U" * (MAX_USER_ID_LENGTH + 1), num_candidates=5)


def test_every_rejected_id_is_rejected_by_the_pattern_not_by_luck():
    """Guards the guard.

    If a future edit widened the pattern, the parametrised tests above
    would still pass for any id that happened to fail some other
    constraint (length, emptiness). This asserts the character class
    itself is what does the work.
    """
    for name, character in INVISIBLE_CHARACTERS.items():
        assert not re.match(USER_ID_PATTERN, f"U123{character}"), (
            f"pattern admits {name} (U+{ord(character):04X})"
        )


def test_an_ascii_control_only_rule_would_have_admitted_every_one_of_them():
    """Why the allow-list, stated as a check rather than a comment.

    This is the rule the allow-list replaced. Every code point above
    passes it, which is precisely how they reached the cache keys.
    """
    ascii_control_only = r"^[^\x00-\x1f]{1,128}$"

    admitted = [
        name
        for name, character in INVISIBLE_CHARACTERS.items()
        if re.match(ascii_control_only, f"U123{character}")
    ]

    assert len(admitted) == len(INVISIBLE_CHARACTERS), (
        "if the old rule no longer admits these, this table has drifted "
        "away from the defect it documents"
    )
