# Audit Register

Stable identifiers for every review finding, so an item cannot be
accidentally closed because a number was reused between review rounds.
Ordinal numbers from individual review documents are deliberately not
used as identifiers here.

**Statuses**: `verified closed` (fix implemented, regression test added,
clean CI passed, evidence regenerated) · `partially closed` (code
changed, but evaluation, coverage or documentation incomplete) ·
`accepted limitation` (deliberate tradeoff, disclosed) · `open`.

Baseline for the current round: `86f26d002100a70cc81965a07092f0888dbe1524`.

---

## EVAL-PROVENANCE-01 — Evaluation reports can carry incorrect provenance
**Severity** Critical · **Status** open

Reports are generated after the fact from previously produced raw JSON,
attaching the *current* commit and manifest without establishing that
the current code produced those results. Existing reports also contain
null denominators and stale configuration.

**Remaining** Generate reports during the evaluation run; record dirty-tree
status, dataset and split hashes, seeds and sampling policy; refuse
generation from a dirty tree; strict per-report schemas; rerun every
licensed-data evaluation from a clean commit.

---

## EVAL-RECONCILIATION-02 — End-to-end reconciliation mis-counts repeated clicks
**Severity** High · **Status** partially closed
**Fix commits** `1de8dff`, `ec53440`

The original `[n1,n2,n3] + [n3]` duplication is fixed by multiset
difference. **Residual, reproduced:** multiset subtraction cannot tell a
pre-window occurrence from an incorporated in-window one. Pre-window
history `[n1,n3]` plus a genuine new in-window click of `n3`, with
history not yet advanced, yields `[n1,n3]` where `[n1,n3,n3]` is correct
— a real click is dropped.

**Resolved** by anchoring on each user's history length at first
encounter: growth since that baseline is exactly what the history
absorbed, and the remainder is genuinely additional. The auditor's case
now yields `[n1,n3,n3]`.

**Measured impact on published numbers.** Across the 2,000-impression
window: 160 impressions had prior in-window clicks, the authoritative
history grew in **0** of them -- MIND's `history` does not advance within
the validation split -- and old and new logic disagree on exactly **1**
impression. End-to-end metrics are therefore unchanged to four decimal
places. The defect was real; its effect on this particular evidence is
negligible, and that is stated rather than either exaggerated or used to
dismiss the fix.

**Remaining** Status stays `partially closed` until the evaluation is
rerun under EVAL-PROVENANCE-01 from a clean commit.

---

## STREAM-IDEMPOTENCY-03 — Duplicate and concurrent events corrupt user state
**Severity** High · **Status** partially closed
**Fix commits** `1de8dff` (rollback), `ec53440` (lost update, type inference)

Rollback on late duplicate delivery is fixed: a duplicate now returns
current state rather than the event's historical snapshot.

**Residual 1, reproduced:** the compare-and-set guards the stored version
but not the *derivation basis*. Two consumers that both load empty state
and then write produce a lost update — C1 applies `n1`, C2 applies a
stale state containing only `n2`, final state `[n2]`, both calls
reporting success.

**Residual 2, reproduced:** the retry path infers event type from whether
the attempted state contains clicked items, so an impression retried for
a user with existing click history is re-applied as a click.

**Resolved** by passing the event's own fields into the atomic script,
which loads current state itself and applies the delta. There is no
caller-computed state to go stale and no event type to infer;
`_reapply` and the version-conflict retry are removed. Verified: two
consumers that both read before writing now retain both events, an
impression stays an impression, and the original rollback case still
holds.

**Remaining** Exercised only against `InMemoryRedis`. The fake
implements the script's contract in Python, so real Lua semantics
(notably `cjson` array encoding) are not covered. Status stays
`partially closed` until this runs against a real Redis in CI.

---

## STREAM-COMMIT-04 — Kafka commit failures handled too weakly
**Severity** Medium · **Status** partially closed
**Fix commit** `1ddd1a1` · **Tests** `tests/test_consumer.py`

Processing continued after an offset commit failure. Because Kafka
offsets are cumulative, the next successful commit would also commit the
failed message, so the previous claim that a failed commit "simply means
redelivery" was wrong -- the message would never be redelivered.

Commits are now retried with bounded exponential backoff
(`COMMIT_RETRY_ATTEMPTS`), failures increment
`stream_commit_failures_total`, and the consumer stops rather than
continue past an unconfirmed offset. The run reports
`stopped_on_commit_failure`.

**Remaining** Only covered by fakes; no integration test against a real
broker with consecutive commit failures.

---

## ARTIFACT-VALIDATION-05 — Content artifact validation incomplete
**Severity** High · **Status** partially closed
**Fix commits** `ccc1106`, `ec53440`

Rejected now: one-dimensional arrays, wrong save width, NaN/Inf,
non-floating save dtype, wrong stored dtype, empty and duplicate ids.
Artifacts carry a payload checksum, and tampering is detected.

**Residual, reproduced:** the loader trusts the artifact's declared
`feature_width` instead of also requiring it to equal the application's
`CONTENT_DIM`. An artifact declaring width 3, with a matching checksum,
loads successfully.

**Resolved** the declared width is now checked against `CONTENT_DIM`
rather than trusted.

**Remaining** The checksum covers matrix bytes only, not shape, dtype or
ids; artifacts predating the metadata fields are still accepted.

---

## ARTIFACT-BUNDLE-06 — Model and content artifacts are not one atomic bundle
**Severity** High · **Status** open

A newly written content artifact can coexist with an older retrieval
model if training fails between writes, so a model can interpret vectors
from a different fitted basis.

**Remaining** Write to a versioned temporary directory; record content
hash, catalog hash, dimensions and transformer version in model
metadata; validate on load; switch an active pointer only after all
artifacts are written; simulate partial training failure.

---

## ARTIFACT-TRANSFORMERS-07 — Fitted transformers unavailable for new articles
**Severity** Medium · **Status** open

The persisted matrix covers the fixed catalog; the fitted TF-IDF/SVD
transformers are not available to project a genuinely new article into
the same basis.

**Remaining** Either persist and validate the fitted transformers, or
state explicitly that this is a fixed-catalog demonstration without
online item onboarding.

---

## EVAL-SPLIT-BOUNDARY-08 — Equal timestamps crossed the chronological boundary
**Severity** High · **Status** verified closed
**Fix commit** `1de8dff` · **Tests** `tests/test_tuning_fold.py`

The split cut by row position, so equal timestamps landed on both sides.
Now cuts on a timestamp with the whole group moving together, refuses
when no strict boundary exists, and reports the realised boundary, gap
and fraction drift.

---

## EVAL-RETRIEVAL-LEAKAGE-09 — Tuning features leak tuning-fold labels
**Severity** High · **Status** open

The ranking model is refit on the fit half, but the retrieval model
producing `retrieval_score` was trained on the whole training split
including the tuning half.

**Remaining** Create the fold before training retrieval; train retrieval
and ranking on fit-half data only; regenerate tuning features from
fit-only artifacts; rerun diversity, freshness and retrieval-depth
comparisons. Until then the tuning results are development evidence
with residual feature leakage.

---

## EVAL-SAMPLING-10 — Tuning experiments use biased first-N samples
**Severity** Medium · **Status** open

`head(1500)` and `head(400)` select the earliest qualifying impressions
rather than a representative sample.

**Remaining** Deterministic seeded or stratified sampling; record seed,
eligible population, time range, user count and sample hash; repeat
across several samples; report sampling variance.

---

## MANIFEST-PATHS-11 — Manifest depends on the caller's working directory
**Severity** Medium · **Status** verified closed
**Fix commit** `efe29be` · **Tests** `tests/test_artifact_manifest.py`

The same deployment reported serving version `9714f1cdc920` from the
repository root and `935041132c2d` from elsewhere, with every artifact
hashing as `absent`. Paths now resolve through `recommender.paths`,
anchored to the repository root or an explicit `RECOMMENDER_DATA_ROOT`.

## MANIFEST-COVERAGE-12 — Manifest omits response-affecting inputs
**Severity** Medium · **Status** open

Popularity, first-seen and durable-feature snapshots are not hashed, so
recommendations can change without the serving version changing.

## FEATURE-FRESHNESS-13 — Durable-feature freshness is not operational
**Severity** Medium · **Status** verified closed (scope decision)
**Fix commit** `efe29be` · **Tests** `tests/test_serving_cache.py`

Staleness was measured against the time the process built the
snapshot, so restarting relabelled a frozen 2019 dataset as freshly
computed. `built_at` and `data_as_of` are now separate, staleness is
measured against the data, a content-derived `snapshot_id` is stable
across restarts, and `/ready` reports age, staleness and an explicit
policy stating the data are frozen and restarting does not refresh
them. `durable_feature_data_age_seconds` exposes the data age.

Automated atomic refresh is future work by agreed scope decision, not
a missing production feature.

## FEATURE-DETERMINISM-14 — Durable features nondeterministic on tied timestamps
**Severity** Medium · **Status** open

## SUPPLY-RUNTIME-LOCK-15 — Production image installs dev and audit tooling
**Severity** Medium · **Status** open

## SUPPLY-DOCKERIGNORE-16 — No restrictive `.dockerignore`
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`

Licensed data, local secrets, Git metadata, virtual environments, caches
and build output are excluded. CI builds the API container successfully
with this configuration.

## STREAM-DURABILITY-17 — Redis may lose acknowledged writes
**Severity** Medium · **Status** partially closed
**Fix commit** `ccc1106`

AOF enabled with `appendfsync everysec`; the ~1s bound is stated in the
configuration.

**Residual** A volume comment still claims every recent-feature record
survives restart, contradicting the stated loss window. No abrupt-kill
recovery test exists, and CI checks connectivity rather than AOF
recovery.

## SCHEMA-EVENT-18 — Event schema validation too permissive
**Severity** Medium · **Status** open

## API-USERID-19 — User ids insufficiently bounded
**Severity** Medium · **Status** partially closed
**Fix commit** `ccc1106`

Bounded to 128 characters; empty ids, ASCII whitespace and ASCII control
characters rejected; applied to both the JSON body and the `/demo` path.

**Residual, reproduced:** the pattern admits non-printing Unicode format
characters. `U1​2` (zero-width space), `‎` and `﻿` are
accepted despite `str.isprintable()` reporting False.

**Resolved** replaced with the positive allow-list
`^[A-Za-z0-9._:-]{1,128}$`. Zero-width space, bidirectional marks and
byte-order marks are now rejected.

**Remaining** Status stays `partially closed` pending explicit
regression tests for each Unicode category.

## FEATURE-TIMEZONE-20 — `hour_of_day` semantics may differ offline vs online
**Severity** Medium · **Status** open

## SUPPLY-IMAGE-PINS-21 — Redis, Kafka and Actions use mutable tags
**Severity** Medium · **Status** open

## API-EXPOSURE-22 — API bound to all interfaces
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`

Binds `127.0.0.1` by default; `API_BIND_HOST` widens it deliberately.

---

## Documentation findings

| ID | Title | Status |
|---|---|---|
| DOC-METRIC-PROMINENCE-23 | Candidate-list metrics more prominent than end-to-end | open |
| DOC-RERANK-CONTRADICTION-24 | README and reranking doc disagree | open |
| DOC-RETRIEVAL-SUPERSEDED-25 | Superseded retrieval conclusions remain | open |
| DOC-UNTOUCHED-TERM-26 | "Untouched" split terminology inaccurate | open |
| DOC-MINFRESH-EVIDENCE-27 | Minimum-fresh comparison claimed but absent from committed report | open |
| DOC-BANDIT-COUNTS-28 | Hardcoded Bandit counts go stale | open |
| DOC-OVERCLAIM-29 | Claims stronger than implementation | open |
| DOC-SETUP-ENCODING-30 | POSIX activation on Windows; replacement characters | open |
| DOC-LOCKGEN-31 | Lock-regeneration instructions incomplete | open |
| TEST-STARLETTE-32 | TestClient deprecation warning | accepted limitation |
| TEST-SVD-WARNING-33 | Degenerate SVD warning in a test | open |

## Accepted limitations

| ID | Title |
|---|---|
| LIMIT-TORCH-AUDIT-34 | CPU-only torch not advisory-scanned |
| LIMIT-NO-FINAL-SPLIT-35 | No untouched final evaluation split remains |
| LIMIT-QUALITY-36 | Recommendation quality remains low |
| LIMIT-COLDSTART-37 | Featureless users receive one popularity slate |
| LIMIT-RECENCY-CONFOUND-38 | Recency analysis confounded by user composition |
| LIMIT-JUDGMENT-PARAMS-39 | Some parameters rest on product budgets |
| LIMIT-PUBLIC-CI-40 | Public CI cannot reproduce licensed-data metrics |
| LIMIT-IDEMPOTENCY-WINDOW-41 | Idempotency bounded by claim retention |
| LIMIT-LEXICAL-ONLY-42 | Lexical validation is not semantic verification |
| HIST-CI-CLAIM-43 | An earlier report described local runs as green CI while CI was red |

---

## Status summary

Remediation and evaluation regeneration are in progress. Current
machine-readable evaluation reports should be treated as development
evidence until the provenance and leakage corrections
(EVAL-PROVENANCE-01, EVAL-RETRIEVAL-LEAKAGE-09, EVAL-SAMPLING-10) are
complete and the affected evaluations have been rerun.

This project is **not** in a state where all audit findings are closed.
