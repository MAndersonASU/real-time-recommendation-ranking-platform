# Engineering review

Current status of the maintainer-led review of this repository. This was
not an independent audit; no third party verified these findings.

## Where it stands

Of **23 primary findings**: 20 verified closed, 1 partially closed by an
explicit scope decision, 2 accepted limitations.

| Item | Status |
|---|---|
| STREAM-COMMIT-04 — commit-failure behaviour against a live broker | partially closed by scope |
| DOC-RERANK-CONTRADICTION-24 | reopened 2026-08-26; addressed, pending independent check |
| DOC-RETRIEVAL-SUPERSEDED-25 | reopened 2026-08-26; addressed, pending independent check |
| DOC-UNTOUCHED-TERM-26 | reopened 2026-08-26; addressed, pending independent check |

A documentation review on 2026-08-26 reopened the three findings above,
which had been marked closed on incomplete evidence, and raised further
findings covering stale metric tables, stale architecture and
serving-contract text, an unrenamed explanation metric, and overstated
reproducibility and CI claims. Those are addressed and await an
independent check.

## Evidence status

Seven legacy evaluation tables match their recorded measurements but do
not yet have committed, provenance-valid machine-readable reports. Their
reports require clean-tree artifact reconstruction and full
recomputation. No report was backfilled with inferred or false
provenance.

Not every headline result is report-backed yet, and not all documentation
findings are closed.

## Why reports are not backfilled

`recommender.evaluation.reports.validate` refuses a report produced from
a dirty working tree, because the commit it records would not describe
the code that produced the numbers. Republishing an older local result
under a current commit would assert a provenance that is not true — the
exact failure EVAL-PROVENANCE-01 was raised about. The validator has not
been weakened and no field has been hand-filled.

Publishing those seven requires: rebuild the licensed-data artifacts from
a clean commit, validate the bundle, re-run each evaluation with
`--output-dir` pointing outside the tree, then commit the reports in a
dedicated commit whose recorded `source_commit` is the clean commit that
computed them.

## Full records

- [`engineering-review-register.md`](engineering-review-register.md) — every finding, with fix commits and verification
- [`engineering-review-and-hardening.md`](engineering-review-and-hardening.md) — scope, methodology and disclosed limitations
- [`limitations.md`](limitations.md) — accepted limitations that no fix is planned for
