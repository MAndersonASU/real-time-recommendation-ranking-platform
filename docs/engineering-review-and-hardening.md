# Engineering review method and hardening

This page explains how the maintainer-led engineering review was
performed and what areas it strengthened. It is not an independent
audit or an external certification.

Finding-by-finding status belongs in the
[review register](engineering-review-register.md). Detailed experiment
results belong in the [evaluation index](evaluation.md). Keeping those
details in their primary documents prevents this page from becoming a
second, stale copy.

## Review record

| Item | Value |
|---|---|
| Baseline commit | `cd8a4d776ad81b47313e2761e2ba9c3918293c26` |
| Review period | August 24–26, 2026 |
| Editorial update | August 30, 2026 |
| Development system | Windows 11 |
| Clean-environment system | `python:3.11-slim` container |
| CI system | Ubuntu GitHub Actions |

The review covered:

- the live recommendation request;
- offline and serving-path evaluation;
- retrieval and ranking artifacts;
- the streaming consumer and replay producer;
- dependencies, packaging, and the container image;
- operational visibility; and
- repository documentation.

## What was outside the review

- The licensed MIND dataset is not distributed here. A public clone
  cannot reproduce quality metrics until the user supplies it locally.
- Public CI uses synthetic artifacts to verify wiring. It does not
  reproduce published recommendation-quality metrics.
- There is no production deployment. The review therefore makes no
  claim about real traffic, concurrency, or infrastructure latency.

## How the review was performed

The maintainer used:

- static source review of serving, evaluation, and streaming code;
- a clean `python:3.11-slim` installation with no `data/` directory;
- unit and integration tests;
- fail-then-pass checks for new regression tests;
- temporal-leakage and prefix-invariance checks;
- adversarial tests for explanation wording;
- Kafka and Redis restart and redelivery checks;
- smoke tests against the built container;
- `pip-audit`, Bandit, and Ruff scans; and
- a cross-document consistency review.

## What changed

| Area | Improvement | Verification |
|---|---|---|
| Retrieval | Added per-article content features and increased retrieval depth | Retrieval and end-to-end evaluation on local licensed data |
| Evaluation | Added deterministic chronological ordering, timestamp barriers, point-in-time state, and a separate tuning fold | Prefix-invariance, equal-time, and out-of-order tests |
| Explanations | Moved factual claims into structured facts and approved templates; optional rewriting remains off by default | Adversarial wording tests |
| Reproducibility | Persisted the content transform and added Linux CPU-only, hash-verified locks | Clean-container install, `pip check`, and the no-data test suite |
| Streaming | Added user-keyed events, atomic event claims, and deterministic replay IDs | Restart, redelivery, and repeated-replay tests |
| Serving | Narrowed dependency fallbacks and added request correlation and accurate cold-start labels | API failure and cold-start tests |
| Security | Runs as a non-root container, pins the base image by digest, and blocks on dependency audit failures | CI container and audit jobs |
| Observability | Records a complete artifact manifest with lock digest and source commit | Tests that change each tracked field |

## Where to verify the claims

- [GitHub Actions](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml)
  is the source for current CI status, test counts, and coverage.
- `reports/*.json` contains machine-readable experiment results with
  commits, artifact hashes, settings, seeds, denominators, definitions,
  and limitations.
- The `api-container-test` job builds the real image, waits for health,
  checks the non-root user, and sends valid and invalid API requests.
- The `integration-smoke-test` job checks Kafka produce/consume and
  Redis read/write behavior.
- `pip-audit` blocks CI for known vulnerabilities in packages it can
  inspect.
- `bandit -ll` blocks CI for medium- and high-severity findings.

Counts are not copied into this page because they change as the code and
test suite change.

## Bandit low-severity findings

Low-severity findings were reviewed by category. The table lists every
current file for the subprocess category and is checked against a fresh
Bandit scan by the test suite.

| ID | Location | Assessment |
|---|---|---|
| B105 | `data/schema.py`, `evaluation/publish.py` | False positives — Bandit matches identifiers containing "pass". One is a regex for a MIND impression token (`<news_id>-<0\|1>`); the other is the metric key `lexical_policy_pass_rate`. Neither is a credential. |
| B404, B603, B607 | `monitoring/artifact_manifest.py`, `tracking/experiment_log.py`, `evaluation/reports.py`, `evaluation/build_receipt.py`, `evaluation/generate_reports.py`, `features/verify_aof_recovery.py` | Low risk. Each calls `git` or `docker` with a fixed argument list and no user input, either to record result provenance or verify container recovery. The findings remain visible so future call sites receive review. |

A previous B101 finding was corrected. Production code used a bare
`assert` for the paired-sample digest check in
`tracking/recent_features_ablation.py`. Python can remove assertions
when run with optimization, so the code now raises `ValueError`
explicitly. A test prevents production code from reintroducing a bare
assertion.

## `pip-audit` limit

`pip-audit` reports no known vulnerabilities in the packages it can
inspect, but it skips the CPU-only PyTorch package:

```text
torch  Dependency not found on PyPI and could not be audited: torch (2.13.0+cpu)
```

That wheel comes from PyTorch's own package index and uses a version that
has no matching PyPI record. It is pinned and hash-verified, but it is
not checked against the advisory database. This is a disclosed gap, not
an all-clear claim.

## Evaluation conclusions

The review confirmed three important interpretation rules:

1. Development results are not untouched final estimates because the
   validation data informed design choices.
2. Public CI verifies software behavior with synthetic artifacts; it
   does not reproduce licensed-data metrics.
3. Different protocols answer different questions and must not be
   combined into one quality claim.

The minimum-fresh experiment is a useful example. All tested quotas met
the predefined logged-click retention bounds, so the rule selected the
largest tested value, 5. That boundary result does not prove that 5 is
better for users. The deployed value remains 2 as a conservative
product-policy choice. Full numbers, uncertainty bounds, and caveats are
in the
[freshness evaluation](experiments/reranking-freshness.md)
and its
[frozen protocol](experiments/min-fresh-experiment-protocol.md).

The diversity cap remains 3. Its comparison uses predicted relevance,
not logged outcomes, so it should not be presented as a user-benefit
result. Retrieval depth uses clicked-item containment plus a latency
budget and therefore answers a different question.

## Remaining limits

The main limits are:

- end-to-end recommendation quality remains low;
- retrieval is the main quality ceiling;
- users with no history receive the same global-popularity fallback;
- chronological splits mix time effects with changes in user
  composition;
- several product settings depend on judgment-based budgets;
- public CI cannot reproduce licensed-data quality results;
- streaming idempotency is limited by claim retention;
- PyTorch is not advisory-scanned;
- lexical explanation checks cannot guarantee meaning; and
- no untouched final evaluation split remains.

See [project limitations](limitations.md) for the plain-language
explanation of each item.

## Related records

| Record | Contents |
|---|---|
| [Engineering review](engineering-review.md) | Current status summary |
| [Review register](engineering-review-register.md) | Every finding and its evidence |
| [Evaluation index](evaluation.md) | Current result pages and reports |
| [Change log](../CHANGELOG.md) | User-visible and architectural changes |
