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
**Severity** Critical · **Status** code complete, awaiting rerun
**Tests** `tests/test_reports.py`

Reports were generated after the fact from previously produced raw JSON,
attaching the *current* commit and manifest without establishing that
the current code produced those results. Existing reports also contained
null denominators and stale configuration.

**Fixed** Each evaluation now builds and writes its own report while it
holds its results (`recommender.evaluation.publish`), so the recorded
commit describes the code that ran. `build_report` refuses a dirty
working tree outright rather than recording a caveat. Schema version 2
adds `provenance` (commit, tree-clean flag, generated-at, evaluation
module) and `sampling`, fingerprints the catalog and every split file,
and rejects a report with an undefined metric, a null denominator, or a
rate outside `[0, 1]`. `recommender.evaluation.generate_reports` is now
a validator, run in public CI against the committed reports only —
it reads no licensed data.

The four schema-version-1 reports were removed rather than re-stamped:
re-labelling them under the new contract is exactly the defect this
closes.

**Remaining** Republish all four reports from a clean commit of this
code, on a machine holding the licensed dataset.

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
**Severity** High · **Status** verified closed
**Fix commit** `5a3ea8e` · **Tests** `tests/test_bundle.py`

A newly written content artifact could coexist with an older retrieval
model if training failed between writes, so a model could interpret
vectors from a different fitted basis.

**Fixed** `recommender.retrieval.bundle` records the retrieval model
hash, content artifact hash, catalog hash, both dimensions and the
catalog item count in a single manifest, written atomically via
`os.replace` only after every artifact it covers exists. `validate_bundle`
raises `BundleError` on any mismatch at load. If training fails partway,
the previous manifest stays in place and serving refuses the mismatched
set rather than loading a new content matrix against an old model.

The fit-half bundle exercises this a second time: it writes its own
manifest to its own path, and the two bundles cannot overwrite each
other (`tests/test_fit_only_bundle.py`).

---

## ARTIFACT-TRANSFORMERS-07 — Fitted transformers unavailable for new articles
**Severity** Medium · **Status** accepted limitation

The persisted matrix covers the fixed catalog; the fitted TF-IDF/SVD
transformers are not available to project a genuinely new article into
the same basis.

**Decision** Accepted as a scope boundary rather than closed. This is a
fixed-catalog research platform evaluated against a frozen MIND
snapshot; it has no online item-onboarding path, so there is no
production flow in which a genuinely new article would need projecting.
Persisting the transformers would add an artifact whose correctness
nothing in this system exercises.

Stated explicitly rather than left implicit: **a new article cannot be
served by the content-aware retrieval path without refitting.**
Recorded in `docs/limitations.md`.

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
**Severity** High · **Status** code complete, awaiting rerun
**Tests** `tests/test_fit_only_bundle.py`

The ranking model was refit on the fit half, but the retrieval model
producing `retrieval_score` was trained on the whole training split
including the tuning half — so the fold was held out from one model and
not the other. The fitted feature context (popularity counts, first-seen
dates) had the same problem.

**Fixed** A second, separate bundle:
`recommender.retrieval.train_fit_only` trains a two-tower model on
fit-half impressions only, using the same `TUNE_FOLD_SEED` the fold
itself uses, and writes `two_tower_model_fit_only.pt`,
`item_content_fit_only.npz` and `bundle_fit_only.json`.
`recommender.ranking.build_dataset_fit_only` rebuilds the ranking
features from that model with the context fitted on fit rows alone, into
`ranking/train_fit_only.parquet`. `verify_tuning_decisions` prefers that
table and records which one it used in every section's output, so a run
that fell back to the leaked table cannot be mistaken for a clean one.

The deployed artifacts are untouched by design. The fit-half model is
trained on 80% of the data specifically so it can be honest about the
fold, which makes it a worse model to serve; substituting it would trade
real serving quality for an evaluation property. A test asserts the two
bundles' paths stay distinct.

**Remaining** Build the fit-half bundle and rerun the diversity,
freshness and retrieval-depth comparisons from a clean commit. Until
that rerun lands, the published tuning results remain development
evidence with residual feature leakage.

---

## EVAL-SAMPLING-10 — Tuning experiments use biased first-N samples
**Severity** Medium · **Status** code complete, awaiting rerun
**Tests** `tests/test_sampling.py`

`head(1500)` and `head(400)` selected the earliest qualifying
impressions rather than a representative sample. Because a user's
session sits inside one part of a day, that also restricted every
comparison to whoever happened to be active first.

**Fixed** `recommender.evaluation.sampling` draws a seeded uniform
sample without replacement, over impression ids rather than rows.
Applied at all four biased sites: the end-to-end replay and the
diversity-cap, freshness and retrieval-depth comparisons. Each run
records seed, eligible population, selected count and fraction, distinct
users, time range, and a digest of the selected ids — enough to confirm
a rerun drew the same sample without publishing licensed ids. The
end-to-end replay still sorts chronologically after selection, so its
point-in-time guarantees are unchanged.

**Remaining** Republish the affected reports from a clean commit.
Sampling variance across several seeds is not yet measured; the single
seed is recorded, so the figures are reproducible but their sampling
error is unquantified.

---

## MANIFEST-PATHS-11 — Manifest depends on the caller's working directory
**Severity** Medium · **Status** verified closed
**Fix commit** `efe29be` · **Tests** `tests/test_artifact_manifest.py`

The same deployment reported serving version `9714f1cdc920` from the
repository root and `935041132c2d` from elsewhere, with every artifact
hashing as `absent`. Paths now resolve through `recommender.paths`,
anchored to the repository root or an explicit `RECOMMENDER_DATA_ROOT`.

## MANIFEST-COVERAGE-12 — Manifest omits response-affecting inputs
**Severity** Medium · **Status** verified closed
**Fix commit** `0945f55` · **Tests** `tests/test_artifact_manifest.py`

Popularity, first-seen and durable-feature snapshots were not hashed, so
recommendations could change without the serving version changing.

**Fixed** The manifest now carries `behaviour_splits`, fingerprinting the
train and validation behaviour files those snapshots are derived from.
The derivation is deterministic given the code, whose commit is already
in the manifest, so inputs plus code identify the outputs — hashing the
derived frames themselves would add startup cost without adding
information.

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
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e` · **Tests** `tests/test_ranking_features.py`

Two impressions sharing a timestamp were resolved in whatever order the
source supplied, so the same data could produce different durable
features.

**Fixed** `compute_durable_features` sorts on `("time", "impression_id")`
with a stable mergesort before taking each user's last row, making
`impression_id` the deterministic tiebreak.

## SUPPLY-RUNTIME-LOCK-15 — Production image installs dev and audit tooling
**Severity** Medium · **Status** verified closed
**Tests** CI job `locked-install-test`

A single combined lock put pytest, bandit, pip-audit, ruff and pip-tools
into the production image — packages that never execute in serving but
are present to be exploited.

**Fixed** Split into `requirements-lock.txt` (62 packages, runtime only,
what the container installs) and `requirements-dev-lock.txt` (94
packages, a strict superset for CI and local work). Both are
hash-pinned and regenerated together. CI asserts the absence of each dev
tool from the runtime lock, then installs the runtime lock alone into
its own virtualenv and imports the serving app from it, so a runtime
dependency that only the dev lock carries fails there rather than in
production.


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
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e` · **Tests** `tests/test_streaming_schema.py`

**Fixed** `InteractionEvent.validate()` enforces an allow-list of
sources, a 128-character identifier bound, a character pattern, RFC 3339
timestamps and a fixed field set. Event ids are uuid5-derived from the
event's own content, so the same real event produces the same id across
producers rather than a fresh one per send.

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
**Severity** Medium · **Status** verified closed
**Fix commit** `0945f55` · **Tests** `tests/test_ranking_features.py`

Two definitions of `hour_of_day` existed, one for training and one for
serving, so a model trained on one convention could be served under the
other.

**Fixed** A single `hour_of_day(timestamp)` definition, used by both
paths.

## SUPPLY-IMAGE-PINS-21 — Redis, Kafka and Actions use mutable tags
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e`

A tag is mutable: whoever controls the image or action repository can
repoint it, and every later run silently executes different code.

**Fixed** `docker-compose.yml` pins Redis and Kafka by image digest;
every GitHub Action is pinned by commit SHA, with a trailing comment
recording which release each SHA was so an intentional upgrade stays
readable.

## API-EXPOSURE-22 — API bound to all interfaces
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`

Binds `127.0.0.1` by default; `API_BIND_HOST` widens it deliberately.

---

## Documentation findings

| ID | Title | Status |
|---|---|---|
| DOC-METRIC-PROMINENCE-23 | Candidate-list metrics more prominent than end-to-end | verified closed |
| DOC-RERANK-CONTRADICTION-24 | README and reranking doc disagree | verified closed |
| DOC-RETRIEVAL-SUPERSEDED-25 | Superseded retrieval conclusions remain | verified closed |
| DOC-UNTOUCHED-TERM-26 | "Untouched" split terminology inaccurate | verified closed |
| DOC-MINFRESH-EVIDENCE-27 | Minimum-fresh comparison claimed but absent from committed report | verified closed |
| DOC-BANDIT-COUNTS-28 | Hardcoded Bandit counts go stale | verified closed |
| DOC-OVERCLAIM-29 | Claims stronger than implementation | verified closed |
| DOC-SETUP-ENCODING-30 | POSIX activation on Windows; replacement characters | verified closed |
| DOC-LOCKGEN-31 | Lock-regeneration instructions incomplete | verified closed |
| TEST-STARLETTE-32 | TestClient deprecation warning | accepted limitation |
| TEST-SVD-WARNING-33 | Degenerate SVD warning in a test | verified closed |

**DOC-METRIC-PROMINENCE-23** — the README led with hit rate@10 = 0.6828,
which is the candidate-list protocol (rank a few dozen supplied items
that already contain the click), while the end-to-end figure sat in a
linked document. Both protocols are now shown, the end-to-end one first
and labelled as the number to judge the system by.

**DOC-MINFRESH-EVIDENCE-27** — the comparison now runs and is published.
It shows the deployed minimum-fresh quota of 2 is **not** selected by
its own rule at any budget tested (the rule picks 5, 5 and 3). Recorded
as a conservative product choice rather than a measured one.

**DOC-BANDIT-COUNTS-28** — the transcribed count ("six low-severity
findings") had already gone stale; the real count was ten. The count is
no longer transcribed, matching how the same document already treats
test counts.

**DOC-SETUP-ENCODING-30** — worse than described. `docs/retrieval-evaluation.md`
contained three raw `0x97` bytes (cp1252 em-dashes written without
encoding) in an otherwise UTF-8 file, making the whole document
undecodable by any strict UTF-8 reader. Repaired. The README's
virtualenv activation line also assumed one platform and now covers
PowerShell, Git Bash and POSIX separately.

**DOC-LOCKGEN-31** — the documented `pip-compile` command produced a
single combined lock and omitted the PyTorch CPU index, so following it
would have pulled the multi-gigabyte CUDA wheel into the runtime set.
Both commands are now documented.

**TEST-SVD-WARNING-33** — caused by a single-user fixture leaving the
interaction matrix with no between-user variance. Fixed by making the
fixture non-degenerate, not by silencing the warning.

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

All four published reports have been regenerated from clean commits of
the corrected code, with provenance recorded by the run that measured
them. The tuning comparisons ran against the leakage-free fit-half
feature table (`tune_fold_leakage: false`).

**Not closed**, and each is recorded above with what remains:

- STREAM-IDEMPOTENCY-03 — the Lua path is proven against the in-process
  Redis stand-in, not a real Redis in CI.
- STREAM-COMMIT-04 — commit-failure behaviour is tested against a fake
  broker, not a real one.
- STREAM-DURABILITY-17 — the AOF bound is configured and documented but
  not demonstrated by an abrupt-kill recovery test.
- API-USERID-19 — the identifier pattern is enforced; Unicode category
  behaviour is not separately tested.
- ARTIFACT-VALIDATION-05 — the content checksum covers the matrix bytes;
  shape, dtype and id ordering are validated separately rather than
  folded into one fingerprint.
- EVAL-SAMPLING-10 — sampling is representative, seeded and recorded,
  but variance across several seeds is not measured, so the published
  figures' sampling error is unquantified.

Accepted limitations are listed above and are not counted as closed.

This project is **not** in a state where all audit findings are closed.
