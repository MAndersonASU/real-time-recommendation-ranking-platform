# Engineering review

This page summarizes the repository's maintainer-led engineering review.
It was not an independent audit, and no third party verified the
findings.

## Current status

Of **35 primary findings**: 32 verified closed, 1 partially closed by an
explicit scope decision, 2 accepted limitations, 0 open.

The [review register](engineering-review-register.md) is authoritative.
It lists every finding, its evidence, its final status, and the commit
that addressed it.

The original review contained 23 findings. Later verification added 12
more and reopened several earlier findings whose evidence was
incomplete. The reopened documentation findings and all later findings
are now verified closed.

## Evidence status

Each headline result family in the
[evaluation index](evaluation.md) has a committed machine-readable
report with valid provenance. Historical and operational measurements
outside that contract state their own verification limits.

One rerun changed a published conclusion: candidate retrieval is now
the largest service operation, rather than reranking. The
[serving latency report](experiments/serving-latency.md) keeps both
measurements and explains why they differ.

`STREAM-COMMIT-04` remains partially closed because live-broker
commit-failure testing is outside the current scope. The two accepted
limitations are disclosed properties of the project, not unresolved
documentation work.

## Why reports are not backfilled

`recommender.evaluation.reports.validate` refuses a report produced from
a dirty working tree. Otherwise, the recorded commit would not fully
describe the code that produced the result. Older local results were not
relabeled under newer commits, and no provenance field was filled by
hand.

For the missing reports, the maintainer rebuilt licensed-data artifacts
from a clean commit, validated the bundle, ran each evaluation with its
output outside the repository, and then committed the reports. Each
report's `source_commit` identifies the code that computed it.

Serving latency was run after Redis became available. Its artifact
bundle matched the build receipt byte for byte.

## Review documents

| Document | Purpose |
|---|---|
| [Review register](engineering-review-register.md) | Finding-by-finding evidence and status |
| [Review method and hardening](engineering-review-and-hardening.md) | Scope, checks, and security review |
| [Project limitations](limitations.md) | Accepted limits that are not planned fixes |
