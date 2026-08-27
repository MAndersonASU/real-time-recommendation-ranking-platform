"""Scan the tracked tree for committed credentials.

Grepping for the word "secret" matches "secretly" and misses an actual
key, so this looks for the shapes credentials take instead:

1. **Provider patterns** — literal formats that are unambiguous on
   sight (PEM blocks, ``AKIA...``, ``ghp_...``). Any match is a finding.
2. **Secret-named assignments** — a quoted literal assigned to a name
   like ``password`` or ``api_key``, kept only when its Shannon entropy
   says it is not a placeholder.

Entropy is applied *only* to secret-named assignments, never to the file
at large: this repository commits SHA-256 artifact hashes by design, and
they are maximally high-entropy. A global entropy sweep would report
every one of them and be switched off within a week.
"""

from __future__ import annotations

import math
import pathlib
import re
import subprocess
from collections import Counter

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCANNED_SUFFIXES = {
    ".py", ".md", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".sh", ".txt", ".env", ".sql", ".js", ".ts", "",
}

# This file states credential shapes in order to detect them.
SELF = pathlib.Path(__file__).name

PROVIDER_PATTERNS: dict[str, re.Pattern[str]] = {
    "PEM private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Stripe live key": re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b"),
    "JSON web token": re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
    ),
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z_]*(?:password|passwd|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key))\b\s*[:=]\s*"
    r"[\"']([^\"'\n]{8,})[\"']"
)

# A value is a placeholder if it says so. Documented individually rather
# than as a blanket "ignore tests" rule.
PLACEHOLDER = re.compile(
    r"(?i)^(?:"
    r"change[_-]?me|example|sample|dummy|placeholder|redacted|unset|none|"
    r"your[-_].*|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|\.\.\.|x{3,}|"
    r"test[-_]?(?:password|secret|token|key|value)?|"
    r"fake[-_].*|not[-_]a[-_].*|localhost.*|postgres|sqlite.*|redis"
    r")$"
)

# Values that are structurally not credentials.
NOT_A_VALUE = re.compile(
    r"(?i)^(?:"
    r"[a-z_]+\.[a-z_.]+|"          # a dotted reference, e.g. settings.redis
    r"os\.environ.*|"              # an environment lookup
    r"[a-z_]+\([^)]*\)|"           # a call
    r"(?:true|false|null)|"
    r"[/.][\w/.\-]*|"              # a path
    r"https?://.*"
    r")$"
)

# Exact literals that are known not to be credentials, each with the
# reason it appears. Individual values only -- never a file, directory or
# pattern exemption, so a real key added beside one is still caught.
ACCEPTED_LITERALS: dict[str, str] = {
    # Exercises URL-escaping of reserved characters in redis_url_with_auth();
    # the special characters are the point of the fixture.
    "p/ss@w:ord": "tests/test_config.py escaping fixture",
}

ENTROPY_FLOOR = 3.0  # bits per character


def shannon_entropy(value: str) -> float:
    """Bits of entropy per character."""
    if not value:
        return 0.0
    counts = Counter(value)
    total = len(value)
    return -sum(
        (n / total) * math.log2(n / total) for n in counts.values()
    )


def tracked_files() -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    paths = []
    for name in out.split("\0"):
        if not name:
            continue
        path = ROOT / name
        if path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if path.name == SELF or not path.is_file():
            continue
        paths.append(path)
    return sorted(paths)


TRACKED = tracked_files()


def scan(text: str) -> list[str]:
    """Every credential-shaped finding in one file's text."""
    found = []
    for label, pattern in PROVIDER_PATTERNS.items():
        if pattern.search(text):
            found.append(label)
    for name, value in SECRET_ASSIGNMENT.findall(text):
        if value in ACCEPTED_LITERALS:
            continue
        if PLACEHOLDER.match(value) or NOT_A_VALUE.match(value):
            continue
        if shannon_entropy(value) < ENTROPY_FLOOR:
            continue  # a word, not a generated credential
        found.append(f"{name}={value[:4]}... (entropy "
                     f"{shannon_entropy(value):.1f})")
    return found


@pytest.mark.parametrize(
    "path", TRACKED, ids=[str(p.relative_to(ROOT)).replace("\\", "/") for p in TRACKED]
)
def test_no_committed_credentials(path: pathlib.Path) -> None:
    """No tracked file carries a credential."""
    text = path.read_text(encoding="utf-8", errors="replace")
    assert not scan(text), f"{path.relative_to(ROOT)}: {'; '.join(scan(text))}"


@pytest.mark.parametrize(
    "sample",
    [
        "-----BEGIN RSA PRIVATE KEY-----",
        "aws_key = 'AKIAIOSFODNN7EXAMPLE'",
        "token = 'ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8'",
        "slack = 'xoxb-2f4a91c7e8-Zq3'",
        "password = 'Tq7#zR2v!Lm9Xw4E'",
        "api_key: 'k3J8vQ2mZ1pR7yT4nB6xW9'",
    ],
)
def test_credential_shapes_are_detected(sample: str) -> None:
    """A real credential in any supported shape is caught."""
    assert scan(sample), f"missed: {sample!r}"


@pytest.mark.parametrize(
    "sample",
    [
        # The word, not a credential — what the previous grep matched.
        "the streaming replay secretly re-processes data",
        # Committed by design: artifact hashes are high-entropy.
        '"two_tower_model_sha256": "0fdc2b141f14a9c3b7e2d8f01a4c6b9e"',
        # Configuration that defers to the environment.
        "redis_password = os.environ.get('REDIS_PASSWORD')",
        'password: "${REDIS_PASSWORD}"',
        "password = 'changeme'",
        "api_key = 'your-api-key-here'",
    ],
)
def test_non_credentials_are_not_flagged(sample: str) -> None:
    """Words, hashes and environment references are not credentials."""
    assert not scan(sample), f"false positive: {sample!r}"
