"""CI-COVERAGE-WORDING-68: the comment above CI's coverage-floor step
claimed "current coverage is ~64%"; a full run at that same point in
history actually measured 61.28%. The number goes stale on the very
next commit either way -- this guards against a specific current
percentage creeping back into the comment, not against the number
itself being wrong at any one moment.
"""

import re
from pathlib import Path

CI_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"

# Catches "current coverage is 62%", "coverage is ~64.2%", etc. --
# deliberately not matching `--cov-fail-under=60` (an enforced floor is
# not a coverage-is-X claim) or a bare percent sign elsewhere.
_CURRENT_COVERAGE_CLAIM_RE = re.compile(r"coverage is\s*~?\d+(\.\d+)?%")


def test_ci_yml_does_not_claim_a_current_coverage_percentage():
    text = CI_YML.read_text(encoding="utf-8")

    match = _CURRENT_COVERAGE_CLAIM_RE.search(text)
    assert match is None, (
        f"ci.yml claims a current coverage percentage ({match.group()!r}), which goes "
        f"stale on the next commit -- state only the enforced --cov-fail-under floor"
    )


def test_ci_yml_still_enforces_the_coverage_floor():
    text = CI_YML.read_text(encoding="utf-8")

    assert "--cov-fail-under=60" in text
