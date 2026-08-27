# Engineering review

Current status of the maintainer-led review of this repository. This was
not an independent audit; no third party verified these findings.

## Where it stands

Of **23 primary findings**: 20 verified closed, 1 partially closed by an
explicit scope decision, 2 accepted limitations.

| Item | Status |
|---|---|
| STREAM-COMMIT-04 — commit-failure behaviour against a live broker | partially closed by scope |
| DOC-RERANK-CONTRADICTION-24 | verified by review cross-check at `80fbf52` |
| DOC-RETRIEVAL-SUPERSEDED-25 | verified by review cross-check at `80fbf52` |
| DOC-UNTOUCHED-TERM-26 | verified by review cross-check at `80fbf52` |

A documentation review on 2026-08-26 reopened the three findings above,
which had been marked closed on incomplete evidence, and raised further
findings covering stale metric tables, stale architecture and
serving-contract text, an unrenamed explanation metric, and overstated
reproducibility and CI claims. A subsequent maintainer-led review,
read-only against the merged state, verified all three -- not an
independent or third-party check.

That same review found eleven further review findings, from false
sampling-provenance claims in the explanation and latency reports through
construction-era vocabulary in source code the documentation guards
never reached. All eleven are verified closed, each against a fix
commit recorded in `docs/engineering-review-register.md`, including two
evaluations rerun from a clean commit under corrected sampling and
republished rather than reworded around unchanged numbers.

## Evidence status

The twelve headline evaluation result families listed in
`docs/evaluation.md` now each have a committed, provenance-valid
machine-readable report. No report was backfilled with inferred or
false provenance. Other historical and operational measurements
throughout the documentation are real but are not part of this
twelve-report contract; each states its own verification scope in the
document it appears in.

Publishing the last of them changed a result. The serving-latency
measurement, re-run against the current artifact bundle, contradicts the
table recorded on 2026-08-21: candidate retrieval is now the dominant
stage, not reranking. The pipeline changed underneath that table, and
`docs/experiments/serving-latency.md` records both measurements and the
reason they differ.

Every review finding raised through this pass is now closed.
STREAM-COMMIT-04 remains partially closed by an explicit scope decision,
and the accepted limitations listed in the register are not counted as
closed either -- neither is a documentation gap still being chased, both
are permanent, disclosed properties of this project's scope.

## Why reports are not backfilled

`recommender.evaluation.reports.validate` refuses a report produced from
a dirty working tree, because the commit it records would not describe
the code that produced the numbers. Republishing an older local result
under a current commit would assert a provenance that is not true — the
exact failure EVAL-PROVENANCE-01 was raised about. The validator has not
been weakened and no field has been hand-filled.

All seven outstanding evaluations were published exactly that way: the
licensed-data artifacts were rebuilt from a clean commit, the bundle was
validated, each evaluation was re-run with `--output-dir` pointing
outside the tree, and the reports were committed in dedicated
report-only commits whose recorded `source_commit` is the commit that
computed them. Serving latency followed last, once a Redis instance was
available; the artifact bundle was verified byte-identical to the build
receipt before it ran, so its numbers are tied to the same build.

## Full records

- [`engineering-review-register.md`](engineering-review-register.md) — every finding, with fix commits and verification
- [`engineering-review-and-hardening.md`](engineering-review-and-hardening.md) — scope, methodology and disclosed limitations
- [`limitations.md`](limitations.md) — accepted limitations that no fix is planned for
