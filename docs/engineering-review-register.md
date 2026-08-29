# Engineering Review Register

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
**Severity** Critical · **Status** verified closed (third pass)
**Fix commits** `d70f1df`, `b73ce6a`, `42aed02`, `c59b199`, `efacb31`, `1251fb4`
**Reports** `d2f97be` · **CI** run 32975126661 (all four jobs green)
**Reports** `63b5443` (published from clean commit `2b91dd4`)
**Tests** `tests/test_reports.py`, `tests/test_tuning_publish.py` · **CI** run 32929791225 on `6ad6e3e` (all four jobs green)

**Reopened after review**, because two gaps made the earlier closure
broader than its evidence. Both are now fixed; the closure is not
claimed again until the reports are republished and CI is green.

**Gap 1 — fit-only artifacts were not recorded.** The tuning report's
`artifacts` block described the *deployed* model, which is exactly the
model the leakage-free comparison exists to avoid, so
`tune_fold_leakage: false` was an assertion about artifacts the report
did not identify. `fit_only_artifact_manifest()` now records full
SHA-256 for the fit-only model, content artifact, bundle manifest,
ranking feature table and training report, plus the fold seed, fold
fraction and training seed. Full digests, not 12-character prefixes.

**Gap 2 — value validation was not recursive.** Range and null checks
ran only over top-level results, and almost every tuning metric is
nested, so a nested rate of 9.0 was accepted. `_validate_metric_values`
now walks dicts and lists to any depth. A null that is a real answer --
a selection rule nothing satisfied -- is permitted only under explicitly
named keys, so "nothing qualified" stays distinguishable from "value
missing".

**Gap 3, found by a later review — definition enforcement was not
recursive either.** Fixing the *value* checks left the *definition*
check comparing only top-level section names, so an invented nested
field (`made_up_score: 0.5`) was published with nothing saying what it
measured. `_metric_leaves` now collects every measurement leaf at any
depth and requires a definition for each. Metadata is exempted through
an explicit `_METADATA_KEYS` allow-list rather than a heuristic, and
comparison-table keys that name a compared *value* (`"0.90"`, `"3"`,
`"1000"`) are treated as coordinates rather than metrics. Twenty-five
nested measurements that had never been defined now are.

**Gap 4, same review — a missing fit-only artifact could be reported as
`"absent"`.** `fit_only_artifact_manifest()` wrote that placeholder
rather than failing, and validation accepted it, so
`tune_fold_leakage: false` -- the report's strongest claim -- could be
published with nothing identifying the model behind it. The manifest now
raises instead of recording a placeholder, and `validate_report` demands
a full lowercase 64-character SHA-256 for all five fit-only artifacts,
plus a well-formed fold seed, fold fraction, training seed and embedding
dimension, whenever a leakage-free run is claimed. A run that honestly
reports `tune_fold_leakage: true` is not required to carry a manifest it
does not have.

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

**Done** All published reports are generated from clean source commit
`125e32a` and published in commit `37e6510`, each recording that source
commit and a verified-clean tree.

---

## EVAL-RECONCILIATION-02 — End-to-end reconciliation mis-counts repeated clicks
**Severity** High · **Status** verified closed
**Reports** rerun from clean source commit `2b91dd4`, published in
`63b5443`; the ambiguous repeated-article case was independently
reproduced and now yields the correct history
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

---

## STREAM-IDEMPOTENCY-03 — Duplicate and concurrent events corrupt user state
**Severity** High · **Status** verified closed
**Fix commit** `125e32a` · **CI** run 33004519430 (`integration-smoke-test`)
**Tests** `recommender.features.verify_lua_idempotency` and
`recommender.features.verify_lua_concurrency` (both CI, real Redis `EVAL`) · **CI** run 32929791225 on `6ad6e3e` (all four jobs green)
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

**Closed.** Two checks, both against real Redis in CI:

`verify_lua_idempotency` covers the sequential contract -- first apply,
accumulation, late duplicate, returned-state agreement, event-type
handling, history bounding.

`verify_lua_concurrency` covers the case that actually mattered and that
no stand-in could reach. Eight threads, each with its own
`redis.Redis`, released together by a `threading.Barrier`, submitting
200 events for one user, repeated over five rounds. It asserts every
unique event applies exactly once, that concurrent redelivery of all 200
changes nothing, and that a mixed batch of duplicates and new events
lands only the new ones.

A shared client would have serialised on its own connection pool and
tested nothing, which is why each thread builds its own. `InMemoryRedis`
runs every call on one thread and therefore reports success regardless
of how the script behaves under contention -- the reason this could not
be covered where the other idempotency tests live.

**The check has demonstrated power.** Run against the pre-fix
read-modify-write design on the same Redis with the same contention, it
loses 167 of 200 updates. It is not a test that passes because nothing
can fail it.

---

## STREAM-COMMIT-04 — Kafka commit failures handled too weakly
**Severity** Medium · **Status** partially closed (accepted for this project's scope)
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
**Severity** High · **Status** verified closed
**Fix commits** `ccc1106`, `ec53440`, `125e32a` (strict schema)
**Reports** `37e6510` · **CI** run 33004519430
**Tests** `tests/test_content_artifact.py` (30 cases)

Rejected now: one-dimensional arrays, wrong save width, NaN/Inf,
non-floating save dtype, wrong stored dtype, empty and duplicate ids.
Artifacts carry a payload checksum, and tampering is detected.

**Residual, reproduced:** the loader trusts the artifact's declared
`feature_width` instead of also requiring it to equal the application's
`CONTENT_DIM`. An artifact declaring width 3, with a matching checksum,
loads successfully.

**Resolved** the declared width is now checked against `CONTENT_DIM`
rather than trusted.

**Closed by a strict versioned schema.** Two further weaknesses were
addressed together:

*Metadata was optional.* An artifact missing `schema_version`,
`feature_width` or `content_sha256` simply skipped the corresponding
check, so the least verifiable artifact in existence received the least
validation -- exactly backwards. All five fields are now required and
`allow_legacy` defaults to `False`. The escape hatch is per-call, used
only by the migration tool, and never by the serving path.

*The checksum covered matrix bytes only.* That left three ways to change
what an artifact means without the digest noticing: reorder the article
ids, change the declared shape, or reinterpret the payload under a
different dtype -- the bytes are identical in each case. The canonical
checksum now covers schema version, shape, dtype, length-prefixed
ordered ids, and matrix bytes. Length prefixing matters: without it
`["ab", "c"]` and `["a", "bc"]` serialise identically.

A pre-schema artifact is still verified against the weaker digest it was written with, so "unverifiable" and "corrupt" stay distinct
claims.

**Existing artifacts were upgraded, not rebuilt**
(`recommender.retrieval.upgrade_content_artifact`). Rebuilding means
refitting TF-IDF and SVD, and SVD axes are defined only up to sign and
ordering, so a refit produces a different valid basis and the trained
item tower would score coordinates it has never seen. The upgrade adds
metadata only, and verifies the matrix is bit-identical before keeping
the result. Because the file bytes change, the bundle manifest has to be
re-published.

**That re-publication was itself a defect** -- the guard described in an
earlier version of this entry checked that the model and catalog hashes
still matched, which is insufficient: those are exactly the files that
stay unchanged when only the content matrix is swapped. Tracked and
fixed as ARTIFACT-MIGRATION-46 below.

---

## ARTIFACT-MIGRATION-46 — Migration tool could bless a foreign content matrix
**Severity** High · **Status** verified closed
**Fix commits** `3b9c8d4`, receipt correction `2548f21`
**Tests** `tests/test_content_artifact_migration.py` (9 cases)
**CI** run 33006941509

Closed after the reviewer independently repeated the foreign-matrix
attack: the migration raised `MigrationError`, refused to refresh the
manifest, and the foreign bundle remained invalid.

**One low-severity correction found in that review.**
`original_manifest_sha256` was computed *after* publication, so it held
the digest of the replacement manifest rather than the one the migration
superseded -- a receipt naming the artifact it created instead of the one
it replaced, which is the opposite of what a receipt is for. The original
bytes are now hashed before anything is republished, and the published
manifest's digest is recorded separately as
`published_manifest_sha256`. Both are needed: a receipt naming only one
cannot be checked against either state. This did not affect the safety
property.

`upgrade_content_artifact` publishes a bundle manifest, so it can defeat
the check that manifest exists to enforce -- and it did. It refreshed a
stale manifest whenever the model and catalog hashes still matched. Those
are precisely the files that remain unchanged when only the content
matrix is replaced, so the guard tested the one thing the attack does not
touch.

**Reproduced end to end:** a valid bundle was created, its content matrix
replaced with entirely different values, model and catalog left alone.
`validate_bundle` correctly refused the foreign matrix. The migration
tool then refreshed the manifest, and `validate_bundle` accepted it. A
matrix from a foreign fitted basis would have been served -- the exact
failure ARTIFACT-BUNDLE-06 exists to prevent.

A second defect in the same path: `upgrade()` overwrote the original
artifact before comparing the migrated matrix, with no rollback if
verification or manifest publication failed.

**Fixed.** The migration now:

1. validates the complete original bundle before anything is modified,
   and refuses outright if it does not already cohere;
2. retains the original bytes for rollback;
3. writes to a temporary path rather than over the original;
4. strict-loads that temporary artifact through the same path serving
   uses;
5. requires ordered ids and matrix values to be bit-identical, compared
   through a `semantic_digest` that covers meaning and ignores packaging;
6. builds the manifest only against that verified artifact;
7. restores the original on any failure, leaving no temporary file.

`_refresh_stale_manifest_only` is **removed**. There is no longer any
path that publishes a manifest without performing a verified migration
in the same run. An already-current artifact with a disagreeing manifest
is now left disagreeing on purpose: this tool cannot distinguish a stale
manifest from a swapped artifact, and guessing is what created the
defect.

A related packaging bug surfaced while testing: `np.savez` appends
`.npz` when a path lacks it, so the temporary file was being written
somewhere other than where verification looked.

**Scope:** this concerns the reusable migration path. The artifacts
already migrated and the retrieval figure published from them are
unaffected -- the retrieval numbers came back byte-identical across the
migration, which is independent evidence the matrix did not change.

---

## ARTIFACT-BUNDLE-06 — Model and content artifacts are not one atomic bundle
**Severity** High · **Status** verified closed (narrowed scope)
**Fix commits** `5a3ea8e`, `efacb31` · **Tests** `tests/test_bundle.py`

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

**Corrected after review.** A missing manifest used to be accepted
unconditionally, including when a model, content matrix and catalog were
all present -- exactly the state a partially failed training run leaves
behind. Any incoherent artifact set could therefore skip the entire
check by having no manifest, which is the one failure mode the check was
written for. An existing test asserted that permissive behaviour, so the
gap was pinned in place rather than caught. The rule is now:

| artifacts | manifest | outcome |
|---|---|---|
| none | none | accepted -- clean clone |
| any | none | **rejected** -- cannot be verified |
| all | present | checked, must match |

`require_manifest=False` remains available per call for a caller that
must tolerate a pre-manifest set; the serving path does not use it.

**Scope, stated rather than implied:** this is mandatory-manifest
fail-closed behaviour, not a versioned artifact directory with an atomic
active-bundle pointer. Only the manifest write is atomic; the artifact
set as a whole is not published through a pointer switch. The stronger
design is the right one for a system that redeploys artifacts under live
traffic, and this project does not.

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
**Severity** High · **Status** verified closed
**Fix commits** `d70f1df`, `efacb31` · **Reports** `63b5443`
**Tests** `tests/test_fit_only_bundle.py` · **CI** run 32929791225 on `6ad6e3e` (all four jobs green)

The published report records the fit-only model's full SHA-256, which
matches the artifact on disk and differs from the deployed model's, so
`tune_fold_leakage: false` is backed by identification rather than
assertion.

**Reopened after review.** The training and feature path was correct,
but `build_dataset_fit_only` checked only that the fit-only model and
content files *existed*. Existence is not coherence: a model from one
fit-half run could pair with a content matrix from another -- two
independent SVD fits -- producing a feature table that looked
leakage-free while the model scored against a basis it never saw.
`validate_bundle()` now runs against `FIT_ONLY_BUNDLE_PATH` before
either artifact loads, with the manifest required rather than optional.

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

**Done** The fit-half bundle was built (101,555 of 126,695 training
impressions, matching the fold) and the comparisons rerun against it.
The published report records `tune_fold_leakage: false`.

The rerun changed a conclusion: the deployed minimum-fresh quota of 2 is
selected by no budget tested — the rule picks 5, 5 and 3. Recorded in
`docs/engineering-review-and-hardening.md` as a conservative product
choice rather than a measured one. **The deployed value was not
changed**; that is a serving-behaviour decision, not a documentation
one.

---

## EVAL-SAMPLING-10 — Tuning experiments use biased first-N samples
**Severity** Medium · **Status** verified closed
**Fix commits** `d70f1df`, `42aed02` · **Reports** `5f19d65`
**Tests** `tests/test_sampling.py` · **CI** run 32892449514 (green)

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

**Done** Reports republished. The correction was material: the old
`head(2000)` prefix reported end-to-end hit rate@10 of 0.0145 against
0.0084 on a representative 5,000-impression sample — an overstatement of
roughly 1.7x. Retrieval and ranking moved in opposite directions between
the two samples, which a fixed prefix cannot reveal.

Sampling **bias** is closed. Sampling **uncertainty** is a separate
finding, tracked as `LIMIT-SAMPLING-UNCERTAINTY-44`, because calling one
finding both "verified closed" and "still open" was self-contradictory.

**Corrected since:** retrieval-depth sampling was computed but never
reached the published report, and the diversity and freshness
descriptions carried no user count or time range because the feature
table has neither column -- both are now joined from the behaviours
split. The report also described its samples as "drawn independently for
each comparison", which was false: diversity and freshness share a seed,
a population and a selection digest. They use the same sample, which is
the right choice for a paired comparison.

The first correction to that wording was itself wrong. A single
`shared_sample` boolean answered "do *all* comparisons share a sample?",
which became False the moment retrieval depth -- a genuinely different
population -- joined the report, and it then described all three samples
as independent while two were provably identical. The report now groups
comparisons by selection digest and names which ones share which
sample.

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
**Fix commits** `efe29be`, `efacb31`
**Tests** `tests/test_serving_cache.py`, `tests/test_snapshot_identity.py`

Staleness was measured against the time the process built the
snapshot, so restarting relabelled a frozen 2019 dataset as freshly
computed. `built_at` and `data_as_of` are now separate, staleness is
measured against the data, and `/ready` reports age, staleness and an
explicit policy stating the data are frozen and restarting does not
refresh them. `durable_feature_data_age_seconds` exposes the data age.

**Reopened and fixed after review: `snapshot_id` delivered neither
property it documented.** It summed `hash(user_id)` over the user set,
which broke both halves of its own docstring:

- Python randomises `str` hashing per process (PEP 456), so the same
  snapshot produced a different id on every restart. Two processes
  returned `f4e32d2dcdbf` and `10351e8a25d3` from identical data.
- Only the user *set* was hashed, never the feature values, so
  recomputing features for the same users at the same `data_as_of` left
  the id unchanged -- the one case where the id most needs to move,
  because serving behaviour changes while the reported version does not.

Every published field of every record now goes into a SHA-256 digest in
sorted user order, with field tags and separators so adjacent values
cannot be confused for one another. `tests/test_snapshot_identity.py`
covers this with real subprocesses under differing `PYTHONHASHSEED`
values, which is the only way to observe hash randomisation at all --
the seed is fixed at interpreter start, so every in-process assertion
passed against the broken implementation. Reverting to the old version
fails five of the ten tests.

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
**Severity** Medium · **Status** verified closed
**Tests** `recommender.features.verify_aof_recovery` (CI, real Redis) · **CI** run 32929791225 on `6ad6e3e` (all four jobs green)

`docker kill` (SIGKILL), not a graceful stop that would pass with AOF
disabled entirely. Both the user's state and the processed-event claims
survive, so a post-crash redelivery is still refused.
**Fix commit** `ccc1106`

AOF enabled with `appendfsync everysec`; the ~1s bound is stated in the
configuration.

CI now performs a real `docker kill` (SIGKILL) and verifies that both
the user's state and the processed-event claims survive, so a post-crash
redelivery is still refused (`verify_aof_recovery`). A graceful stop
would pass even with AOF disabled, which is why the test uses SIGKILL.

## SCHEMA-EVENT-18 — Event schema validation too permissive
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e` · **Tests** `tests/test_streaming_schema.py`

**Fixed** `InteractionEvent.validate()` enforces an allow-list of
sources, a 128-character identifier bound, a character pattern, RFC 3339
timestamps and a fixed field set. Event ids are uuid5-derived from the
event's own content, so the same real event produces the same id across
producers rather than a fresh one per send.

## API-USERID-19 — User ids insufficiently bounded
**Severity** Medium · **Status** verified closed
**Tests** `tests/test_user_id_unicode.py` (50 cases) · **CI** run 32929791225 on `6ad6e3e` (all four jobs green)
**Fix commit** `ccc1106`

Bounded to 128 characters; empty ids, ASCII whitespace and ASCII control
characters rejected; applied to both the JSON body and the `/demo` path.

**Residual, reproduced:** the pattern admits non-printing Unicode format
characters. `U1​2` (zero-width space), `‎` and `﻿` are
accepted despite `str.isprintable()` reporting False.

**Resolved** replaced with the positive allow-list
`^[A-Za-z0-9._:-]{1,128}$`. Zero-width space, bidirectional marks and
byte-order marks are now rejected.

`tests/test_user_id_unicode.py` covers fifteen invisible code points in
leading, interior and trailing positions, and asserts that the old
ASCII-control-only rule would have admitted every one of them.

## FEATURE-TIMEZONE-20 — `hour_of_day` semantics differ offline vs online
**Severity** Medium · **Status** accepted limitation
**Partial fix** `0945f55` · **Tests** `tests/test_ranking_features.py`
**Tracked as** `LIMIT-HOUR-OF-DAY-TIMEZONE-45`

Reclassified after review. Two *definitions* of `hour_of_day` existed,
one for training and one for serving; there is now a single function and
the two paths cannot drift in derivation.

That is not the same as resolving the finding, and marking it closed
overstated the fix. MIND does not document the timezone of its
timestamps, so trained values are dataset-local hours of an unknown
zone, while a live request with no historical anchor falls back to the
UTC wall clock. **The underlying zones still differ.** One function
prevents derivation drift; it cannot reconcile two different clocks.

Closing this for real means removing `hour_of_day`, retraining, and
regenerating every dependent evaluation. The feature was retained
instead, so the honest status is an accepted limitation with a named
cost, not a closure.

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

## Follow-up findings (2026-08-27 verification round)

Eleven findings from a further verification pass, not a continuation of
the numbered set above -- `EVAL-PROVENANCE-58` and `STREAM-MEMORY-60`
reuse the existing `EVAL-*`/`STREAM-*` prefixes because they genuinely
are that kind of finding; the other nine introduce new prefixes for
kinds of gap this register had not previously named
(`REPRO-*`, `DEPLOYMENT-*`, `DATA-PATH-*`, `TIMESTAMP-*`, `BANDIT-*`,
`HTTP-METRICS-*`, `UNKNOWN-*`, `CI-*`). All eleven had a fix committed
and a fail-then-pass regression test on the branch that became
[PR #6](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/pull/6),
verified against real CI (run 33134350323, all four jobs green) and
merged.

**A further external review of that merged state found three of the
eleven fixes were themselves incomplete** -- `REDIS-DEGRADED-PATH-61`
(the circuit breaker's probe claim was not concurrency-safe),
`TIMESTAMP-CONTRACT-64` (the RFC3339 check still accepted several
non-RFC3339 ISO 8601 forms), and `DEPLOYMENT-CONTRACT-62`
(`build-image.sh` warned on a dirty tree but built anyway). Each gap is
recorded in place on its entry below, with its own reproduction, fix
commit, and regression test, rather than silently editing the earlier
account of what shipped in `PR #6` -- the same discipline this
register already applies to itself in EVAL-PROVENANCE-01's account of
being reopened. The other eight findings' fixes were not affected and
are marked verified closed against the same `PR #6` CI run. The three
reopened findings stayed at `open` until their new fixes had their own
green CI run, not asserted from local runs alone.

**A second external review, of the fixes that landed in
[PR #7](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/pull/7),
found each of those same three findings still incomplete a further
time** -- summarized on the follow-up paragraph of each entry below,
with its own reproduction, fix commit and regression test, and
verified against [PR #8](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/pull/8)'s
own CI run (33259679161, all four jobs green) before being marked
verified closed here.

## EVAL-PROVENANCE-58 — Evaluation reports could inherit a manifest env var as their commit
**Severity** Critical · **Status** verified closed
**Fix commit** `912c00a` · **Tests** `tests/test_reports.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

`source_commit()` tried `GIT_COMMIT_SHA` (meant for the container
manifest, which has no `.git` directory) before falling back to a real
`git rev-parse HEAD`, and the validator only checked the field was
nonempty. `GIT_COMMIT_SHA=banana` reproduced it directly: the report's
`source_commit` came back `"banana"` and validation passed. The
12 committed reports' real provenance was unaffected -- their actual
commits are well-formed -- this was a validator weakness, not evidence
their existing provenance is false.

Fixed by resolving `source_commit` from Git HEAD unconditionally and
requiring a 40-character lowercase hex hash. Also added an optional CI
check (skipped on a shallow clone) confirming every recorded
`source_commit` is a real, existing commit and an ancestor of `HEAD`,
and set `fetch-depth: 0` on the job where that check can run.

## REPRO-ORCHESTRATION-59 — `evaluate_all.sh` ran 7 of the 12 published evaluations
**Severity** High · **Status** verified closed
**Fix commit** `5dd91f9` · **Tests** `tests/test_orchestration_scripts.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

The script's own header claimed it ran "every evaluation whose report
is published." It ran 7: retrieval, end-to-end, tuning decisions,
explanations, and the min-fresh experiment were missing, because those
five modules never accepted `--output-dir` at all. `rebuild.sh`
similarly never built the fit-only bundle `tuning-decisions` needs for
a leakage-free comparison. Both scripts also hardcoded the Windows venv
layout, failing on macOS/Linux despite the README documenting both.

Wired `--output-dir` into the five missing modules, added them and the
two fit-only build commands to the scripts, and added venv-layout
detection. A new test statically discovers every module the script
should run from the same `EXPECTED_REPORTS` contract
`generate_reports.py` already enforces, so a future evaluation added
without a matching script line fails this test instead of silently
never running in the orchestrated pass.

## STREAM-MEMORY-60 — `StreamConsumer.user_states` was still unbounded
**Severity** High · **Status** verified closed
**Fix commit** `97ac5e4` · **Tests** `tests/test_consumer.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

An earlier pass bounded `_seen_event_ids` and the monitoring counters'
`distinct_users`/`distinct_items`, with a comment describing the
unbounded-memory problem as fixed -- but `user_states` stayed a plain
dict. A 1,000-user run reproduced it directly: `user_states` held all
1,000 entries while the bounded structures correctly capped at 10.

Added `BoundedUserStates`, an LRU-evicting cache (recently *touched*,
not just recently inserted, survives eviction). For
`SyncingStreamConsumer` this is a disposable read-through cache over
Redis, which stays authoritative, so eviction loses nothing real. The
plain `StreamConsumer` has no other copy of this state, so its
docstring now explicitly scopes it as a finite verification utility,
never wired into a long-running production entrypoint -- confirmed true
today (only `verify_*.py` scripts construct it).

## REDIS-DEGRADED-PATH-61 — A Redis failure fell all the way back to flat popularity
**Severity** Medium · **Status** verified closed
**Fix commits** `b992259`, `be8b5ce` (removes the matching Compose startup gate), `de457c3` (concurrency-safe breaker, below), `5c32706` (probe-release on every exit path, below)
**Tests** `tests/test_cold_start.py`, `tests/test_serving_fallback.py`, `tests/test_redis_circuit_breaker.py`, `tests/test_deployment_contract.py`
**CI** [PR #8](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/pull/8) run 33259679161 (all four jobs green)

**Reopened by external review of the merged fix.** `RedisCircuitBreaker.allow_request()`
computed `now - opened_at >= cooldown` fresh on every call with no
memory of whether a probe had already been dispatched, so once the
cooldown elapsed, every concurrent caller got the same `True` answer
at once -- the thundering herd this breaker exists to prevent, not
fix. Reproduced with an 8-thread `Barrier`: 8 of 8 threads allowed
past cooldown simultaneously, against the class's own docstring
promising exactly one probe. Fixed in `de457c3` with explicit
CLOSED/OPEN/HALF_OPEN states under a lock -- the state transition and
the probe claim happen inside the same locked call that returns
`True`, so only the thread that actually flips the state gets it. The
same 8-thread reproduction, now a regression test, gets exactly 1 of 8.

Redis unavailability was caught the same way as a broken model or
index -- the full retreat to `build_fallback_response`'s flat,
unpersonalized popularity -- even though Redis only supplies one input
(recent clicks) to an already-running pipeline; durable features, the
trained model, and ranking are all unaffected by Redis being down.
Reproduced directly: `build_client()` against a dead port took ~4s
(redis-py's own implicit retry-with-backoff, never configured by this
project), with no explicit retry policy set anywhere.

`get_online_features` now catches a Redis failure and reports it as an
absent recent-features record (the same shape as an ordinary cold
user, distinguished by a narrower `redis_unavailable` flag), so
`recommend()` completes as a real, personalized response on durable
features. A new `RedisCircuitBreaker`, shared on `ServingContext`,
skips the connection attempt entirely once Redis has failed enough
consecutive times. `build_client()` now sets an explicit 0.2s timeout
and no-retry policy. Live-verified against real Docker containers, not
only mocks: Redis stopped mid-run and Redis never started at all both
leave `/ready` degraded but `/recommend` still personalized on durable
features, with the circuit breaker measurably speeding up the third
request onward (~3-4s for the first two, 0.29s for the third).

**Reopened a second time by external review of `de457c3`.** The
concurrency-safe state machine correctly serialised the HALF_OPEN probe
claim, but `get_online_features` only reported `record_success`/
`record_failure` from an `except redis.exceptions.RedisError` clause --
an exception that reached that call for any other reason (malformed
JSON actually stored under the key, `load_recent_features`'s bare
`json.loads`) matched neither the `try` block's success path nor that
`except`, so it reported nothing at all. The breaker's one HALF_OPEN
probe slot, already claimed by `allow_request()`, was never released,
leaving the breaker stuck refusing every later request regardless of
Redis's real health. Reproduced directly with a fake client whose `get`
returns `"not valid json {{{"`: a single call left `allow_request()`
`False` forever afterward.

**Fixed in `5c32706`.** Every exit path from the Redis lookup now
reports exactly one of `record_success`/`record_failure` before
control leaves, including a bare `except Exception` branch that still
re-raises the original exception after reporting the failure -- the
exception is a real bug (corrupted state), not a Redis connectivity
failure, so it is not swallowed, only its effect on the breaker's
bookkeeping is handled. `tests/test_cold_start.py::test_a_malformed_redis_record_still_lets_a_later_request_probe_again`
covers exactly this case and fails on the pre-fix code.

## DEPLOYMENT-CONTRACT-62 — Compose blocked API startup on a Redis dependency the process doesn't have
**Severity** Medium · **Status** verified closed
**Fix commits** `be8b5ce`, `81483fd` (dirty-tree refusal, below), `9cf0852` (self-anchoring, whole-tree refusal, below), `1cf8464` (test-only)
**Tests** `tests/test_deployment_contract.py`
**CI** [PR #8](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/pull/8) run 33259679161 (all four jobs green)

**Reopened by external review of the merged fix.** `build-image.sh`
detected a dirty working tree but only printed a warning and continued
to `docker compose build api` regardless -- Docker copies whatever is
actually on disk into the image (`COPY src/ ./src/`, `COPY pyproject.toml
./`, `COPY requirements-lock.txt ./`) while the image is labeled with
the clean commit unconditionally, the same provenance mismatch this
project already refuses outright for an evaluation report built from a
dirty tree (`recommender.evaluation.reports`). Fixed in `81483fd`: the
script now refuses (exit 1, before invoking docker) when
`git status --porcelain` shows anything dirty under the paths that
actually affect the image (`src/`, `Dockerfile`, `pyproject.toml`,
`requirements-lock.txt`); a change outside those paths still proceeds.
Verified against a real, isolated `git worktree` checkout, not a
simulation: a dirty file under `src/` refuses before the real `docker
compose build` ever runs; a clean tree still completes a real build; a
dirty file under `docs/` is correctly ignored.

`docs/architecture.md` said Redis is optional and startup does not gate
on it (`DOC-FALLBACK-SCOPE-52` above), but `docker-compose.yml`'s `api`
service had `depends_on: redis: condition: service_healthy`, genuinely
blocking container startup until Redis reported healthy.
`build_serving_context` never connects to Redis during startup -- it
only constructs a client object, lazily connected on first real
command -- so this was a real coupling the process itself never had.
Separately, the Dockerfile claimed Compose supplies a real
`GIT_COMMIT_SHA` "automatically"; false, since Compose cannot run a
shell command inline for a build arg and only forwards whatever the
host environment already set.

Removed the `depends_on` gate and live-verified against the containers
with Redis never started at all (not merely stopped): the API still
reached a healthy `/ready` and served real, personalized `/recommend`
responses. Added `build-image.sh`, the committed wrapper that actually
calls `git rev-parse HEAD` before building, and corrected the
Dockerfile's claim.

**Reopened a second time by external review of `81483fd`.** Two
further gaps in the same script. First, `build-image.sh` had no
directory of its own: every command inside it (`git status`,
`git rev-parse`, `docker compose` reading `docker-compose.yml`)
resolved relative to whatever directory the caller happened to be in
when they
invoked it, not the repository the script lives in. Reproduced
directly: running it from an unrelated directory failed outright
("not a git repository") instead of operating on this repository, and
from inside a *different* git repository it would silently have read
that repository's commit and dirty state instead of this one's.
Second, the dirty-tree refusal only checked an enumerated list of
paths (`src/`, `Dockerfile`, `pyproject.toml`,
`requirements-lock.txt`) -- real gaps, since `docker-compose.yml` (the
build context, args and Dockerfile path are all defined there),
`.dockerignore` (controls what actually reaches the build context) and
any Compose override file are just as image-affecting and were not
checked at all, so a dirty `docker-compose.yml` or `.dockerignore`
built without refusing.

**Fixed in `9cf0852`.** The script now anchors itself to its own
directory (`SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)";
cd "$SCRIPT_DIR"`) before running any git or docker command, so its
behaviour no longer depends on the caller's working directory. The
dirty-tree check now covers the whole working tree
(`git status --porcelain`, no pathspec) rather than an enumerated
list, so it cannot miss a build input the list forgot to name, today
or after a future change to the build -- the same trade this project's
evaluation-report provenance check already makes. Verified against a
real, isolated `git worktree` checkout: a dirty `docker-compose.yml`
refuses, a dirty `.dockerignore` refuses, invocation from a third,
unrelated directory still correctly resolves the worktree's own
commit and dirty state, and a clean tree still reaches a real `docker
compose build` invocation. Live-verified once more directly against
this repository with a real Docker daemon: a genuinely dirty
`README.md` refuses before Docker runs, and a clean tree completes a
real image build end to end.

## DATA-PATH-CONSISTENCY-63 — `RECOMMENDER_DATA_ROOT` didn't move most of the project's own paths
**Severity** Medium · **Status** verified closed
**Fix commits** `5dd91f9`, `b992259`, `e615ff2` · **Tests** `tests/test_data_path_consistency.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

`recommender.paths` exists specifically so `RECOMMENDER_DATA_ROOT`
moves every data path a deployment might relocate, but only the
serving-critical artifact paths (the trained model, index, ranking
pipeline) actually went through `data_path()`/`mind_small_path()`.
Every ingestion, evaluation, and tracking module still built its own
path from a bare `Path("data/...")` literal, relative to the process's
working directory, so the override silently didn't apply to most of
the project's own commands.

Migrated all 27 remaining hardcoded constants (58 total across the
project, once the already-correct ones are included). A new test
discovers every `data_path()`/`mind_small_path()` constant statically
(rather than hand-listing modules, which goes stale the moment a new
one is added), then -- in a real subprocess, with a different working
directory and a temporary `RECOMMENDER_DATA_ROOT` -- imports every one
and checks it actually resolves beneath the override; a companion test
bans a bare `Path("data/...")` literal outright, catching a regression
the discovery approach alone would miss (a reverted constant just drops
out of what gets discovered rather than failing loudly).

## TIMESTAMP-CONTRACT-64 — The RFC3339 validator accepted timestamps that aren't RFC3339
**Severity** Medium · **Status** verified closed
**Fix commits** `063bbf5`, `35c01b3` (structural RFC3339 grammar check, below), `28d578d` (range-checked offset, canonical profile documented, below)
**Tests** `tests/test_streaming_schema.py`
**CI** [PR #8](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/pull/8) run 33259679161 (all four jobs green)

The schema's timestamp validator accepted anything
`datetime.fromisoformat` parses -- naive, space-separated, whatever --
for every event regardless of `source`, while its own error message
claimed `"must be an RFC3339 datetime"` (RFC3339 requires a timezone
offset; a naive string is not that). Separately, comments in
`cache.py` and `pipeline.py` called MIND's timestamps "naive-but-UTC by
convention," contradicting this register's own `FEATURE-TIMEZONE-20`
entry above, which correctly says MIND does not document its
timestamps' timezone at all -- the real zone is unknown, not UTC.

Split the check in two: `_is_dataset_local_timestamp` for a replayed
MIND event (still accepts MIND's real naive shape, honestly named and
documented as not RFC3339), and a genuinely strict `_is_rfc3339` --
parseable *and* timezone-aware -- required for any other source.
Corrected the `cache.py`/`pipeline.py` comments to state the real
situation: UTC is a pragmatic, disclosed assumption this project makes
for comparison purposes, not a documented dataset fact.

**Reopened by external review of the merged fix.** "Parseable and
timezone-aware" was still not "RFC3339": `datetime.fromisoformat` is
intentionally more permissive than RFC3339's own grammar, so
`_is_rfc3339` kept accepting real ISO 8601 forms RFC3339 excludes.
Reproduced two concrete false positives: `"2019-11-14 08:00:00+00:00"`
(a space instead of the required `"T"`) and `"2019-11-14T08:00+00:00"`
(seconds omitted, mandatory in RFC3339's `partial-time`). Fixed in
`35c01b3`: a structural regex against RFC3339's actual grammar
(literal uppercase `"T"`, mandatory seconds, a mandatory `"Z"` or
numeric `"+HH:MM"`/`"-HH:MM"` offset) now runs before `fromisoformat`,
which still runs afterward to reject a structurally valid but
calendar-impossible date or time the regex alone can't catch. New
tests cover both reported false positives plus lowercase separators, a
colon-less offset, and impossible dates.

**Reopened a third time by external review of `35c01b3`.** The
structural regex matched an offset shaped like `[+-]\d{2}:\d{2}` without
range-checking the hour or minute, and `datetime.fromisoformat` -- run
afterward specifically to catch calendar-impossible values -- does not
catch this case either: it normalizes an out-of-range offset via
timedelta arithmetic instead of rejecting it, so `+00:60` parsed
successfully as equivalent to `+01:00` rather than raising. Reproduced
directly: `"2019-11-14T08:00:00+00:60"` passed `_is_rfc3339`.

**Fixed in `28d578d`.** The offset's hour and minute are now
range-checked in the regex itself (`(?:[01]\d|2[0-3])` for 00-23,
`[0-5]\d` for 00-59) rather than deferred to `fromisoformat`'s more
permissive arithmetic. This also settled a standing ambiguity: RFC3339
itself permits a lowercase `t`/`z` separator and a UTC leap second
(`23:59:60`), neither of which this project's validator has ever
accepted, and Python's `datetime` cannot represent a leap second at
all. Rather than silently keep a narrower behaviour under a
full-RFC3339 name, the docstring and the validator's own error message
now explicitly describe **this project's canonical profile**:
uppercase `T`/`Z` only, mandatory seconds, a range-checked
`+HH:MM`/`-HH:MM` offset if not `Z`, no leap second -- a deliberately
narrower, fully-specified subset of RFC3339, not full RFC3339. New
tests cover out-of-range offset hours and minutes on both signs and a
leap-second timestamp, confirming all are rejected.

## BANDIT-REVIEW-65 — A real evaluation invariant used `assert`; the Bandit table was stale
**Severity** Medium · **Status** verified closed
**Fix commits** `e615ff2` (assert -> ValueError), `7d5f2ef` (table and guards)
**Tests** `tests/test_recent_features_ablation.py`, `tests/test_bandit_table_sync.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

`recent_features_ablation.py`'s paired-sample digest check used a bare
`assert`, compiled out entirely under `python -O` -- an unpaired
comparison (the two arms scoring different impression samples) could
have silently continued and published. Separately, the Bandit
low-severity findings table (`docs/engineering-review-and-hardening.md`)
claimed findings were "reviewed by category" but listed only 3 of the
6 real files carrying a B404/B603/B607 subprocess finding -- found by
actually re-running Bandit against the checked-out source, not by
re-reading the table.

Replaced the `assert` with an explicit `ValueError`. Updated the table
to list all six files; the category-level assessment (a static
`git`/`docker` argument list, no user input) still holds for all of
them. A new test re-runs Bandit directly and checks the table's file
list against it, so a new subprocess call site fails this test instead
of silently falling out of the table again; a companion test AST-scans
`src/recommender` for any `assert` statement at all.

## HTTP-METRICS-SCOPE-66 — `recommend_requests_total` never saw a 422 or a middleware-level 500
**Severity** Low · **Status** verified closed
**Fix commit** `b992259` · **Tests** `tests/test_app.py`, `tests/test_metrics.py`, `tests/test_dashboard.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

`recommend_requests_total` only ever incremented inside
`recommend_endpoint`'s own body, so a request FastAPI rejected with a
422 before the handler ran, or a middleware-level 500, was real traffic
no metric counted -- reproduced directly against a `TestClient`, where
a malformed `/recommend` body left the counter completely empty. The
dashboard labeled the derived number "Total requests" regardless.

Added `http_requests_total`, recorded once in the access-log middleware
for every response on every route, labeled by the matched route
*template* (not the resolved path, to keep cardinality bounded) and
status class. Renamed the dashboard's label to "Recommend attempts" to
match what `recommend_requests_total` actually measures, and documented
the two metrics' distinct scopes so they can be compared rather than
conflated.

## UNKNOWN-DATA-AGE-67 — Unknown durable-feature data age reported as a false zero
**Severity** Low · **Status** verified closed
**Fix commit** `b992259` · **Tests** `tests/test_metrics.py`, `tests/test_app.py`
**CI** `PR #6` run 33134350323 (all four jobs green)

`/ready` set the durable-feature data-age gauge with
`age_seconds or 0.0`. `None` (the newest-event time is genuinely
unknown, e.g. an empty behaviors frame) and a real `0.0` are both falsy
in Python, so unknown age silently reported as perfectly fresh.

`set_durable_feature_data_age` now sets the gauge to real `NaN` --
Prometheus's own convention for "no value," distinct from every real
age this gauge can otherwise hold -- when the age is unknown, plus a
companion `durable_feature_snapshot_has_known_age` gauge so the same
fact is queryable/alertable without a NaN-aware query.

## CI-COVERAGE-WORDING-68 — CI's coverage comment cited a number already wrong
**Severity** Low · **Status** verified closed
**Fix commits** `912c00a` (wording), `4547c27` (regression test)
**CI** `PR #6` run 33134350323 (all four jobs green)

The comment above CI's coverage-floor command said "current coverage is
~64%"; a full run at that same point in history actually measured
61.28%, and a fresh run today measures 62.20% -- the number goes stale
on the very next commit regardless of which value is written.

Removed the volatile percentage; the comment now states only the
enforced `--cov-fail-under=60` floor and points at running coverage
locally for the real, current number. A new test statically bans a
`"coverage is X%"` pattern from reappearing in the comment.

---

## Documentation findings

| ID | Title | Status |
|---|---|---|
| DOC-METRIC-PROMINENCE-23 | Candidate-list metrics more prominent than end-to-end | verified closed |
| DOC-RERANK-CONTRADICTION-24 | README and reranking doc disagree | verified by review cross-check at `80fbf52` |
| DOC-RETRIEVAL-SUPERSEDED-25 | Superseded retrieval conclusions remain | verified by review cross-check at `80fbf52` |
| DOC-UNTOUCHED-TERM-26 | "Untouched" split terminology inaccurate | verified by review cross-check at `80fbf52` |
| DOC-MINFRESH-EVIDENCE-27 | Minimum-fresh comparison claimed but absent from committed report | verified closed |
| DOC-BANDIT-COUNTS-28 | Hardcoded Bandit counts go stale | verified closed |
| DOC-OVERCLAIM-29 | Claims stronger than implementation | verified closed |
| DOC-SETUP-ENCODING-30 | POSIX activation on Windows; replacement characters | verified closed |
| DOC-LOCKGEN-31 | Lock-regeneration instructions incomplete | verified closed |
| TEST-STARLETTE-32 | TestClient deprecation warning | accepted limitation |
| TEST-SVD-WARNING-33 | Degenerate SVD warning in a test | verified closed |
| DOC-SAMPLING-PROVENANCE-47 | Bounded per-user/impression evaluations took first-N, reported "no sampling" | verified closed |
| DOC-EXPLANATION-METRIC-DEFN-48 | Report metric_definitions still said "faithful / attempted" | verified closed |
| DOC-RETRIEVAL-OVERCLAIM-49 | `every retrieval metric improved 7.6x-13.5x` false of catalog coverage (1.5x) | verified closed |
| DOC-N100-DEPTH-CONFLATION-50 | Frozen N=100 retrieval evaluation conflated with deployed depth 1,000 | verified closed |
| DOC-CATALOG-SIZE-51 | serving-latency.md named 50,704 (distinct-embedding count) as catalog size | verified closed |
| DOC-FALLBACK-SCOPE-52 | architecture.md overstated Redis as required; overbroad fallback claim | verified closed |
| DOC-COLDSTART-STALE-53 | replay/ablation docs described superseded zero-vector-Faiss cold start | verified closed |
| DOC-PROFILING-STALE-54 | profile-hotspots.md/load-test.md presented pre-optimization results as current | verified closed |
| DOC-REVIEW-STATUS-55 | Three reopened findings never marked verified; "audit" language misdescribed review | verified closed |
| DOC-GRAMMAR-GUARD-56 | Two paragraph-opening capitalization errors; guard only checked first paragraph | verified closed |
| SOURCE-VOCABULARY-57 | Construction-sequence labels and tutorial-style wording persisted in source comments and docstrings | verified closed |

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

**DOC-SETUP-ENCODING-30** — worse than described. `docs/experiments/retrieval-evaluation.md`
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

**DOC-RERANK-CONTRADICTION-24, DOC-RETRIEVAL-SUPERSEDED-25,
DOC-UNTOUCHED-TERM-26** — addressed in `80fbf52` (PR #2). A subsequent
maintainer-led review, read-only against the merged state, re-checked
each: the README and reranking doc no longer disagree, the superseded
retrieval conclusion is labelled and does not misattribute today's
weakness to the fixed defect, and every remaining "untouched" claim
either denies it directly or has been reworded. Not an independent or
third-party audit -- the same maintainer, checking their own prior fix
against the current state before relying on it.

**DOC-SAMPLING-PROVENANCE-47** — `evaluate_explanations.py` and
`verify_latency.py` both took the first N distinct users the validation
split happened to list, while their published reports asserted
`FULL_POPULATION`'s "no sampling -- every eligible impression in the
split was evaluated." `replay_evaluation.py` took the first 500 rows in
on-disk order while calling it merely "sampled." All three now draw a
seeded uniform sample (`recommender.evaluation.sampling`), and the two
publishers can no longer default to `FULL_POPULATION` -- `sampling` is
a required argument, enforced by a test at both the call-site and the
signature level. **Fix commit** `0e80e42`. **Reports republished**
`e368521`. **Docs updated** `9e2d4eb`.

**DOC-EXPLANATION-METRIC-DEFN-48** — `metric_definitions` still read
"faithful / attempted" after the metric itself was renamed to
`lexical_policy_passed`. **Fix commit** `0e80e42`.

**DOC-RETRIEVAL-OVERCLAIM-49** — six files claimed `every retrieval metric improved 7.6x-13.5x`;
catalog coverage, in the same results
table, improved 1.5x. Reworded to distinguish the four relevance
metrics from catalog coverage everywhere the claim appeared, plus a
documentation guard matching the exact false shape. **Fix commit**
`94ddf64`.

**DOC-N100-DEPTH-CONFLATION-50** — conclusions.md used the frozen N=100
RQ1 retrieval evaluation's ~97%-absent figure to describe deployability;
current serving retrieves 1,000 candidates, not 100. Rewritten to name
N=100 as that evaluation's own cutoff and cite the actual end-to-end
measurement (14.14% clicked-item containment, 0.84% final hit rate)
for deployability instead. **Fix commit** `94ddf64`.

**DOC-CATALOG-SIZE-51** — serving-latency.md's cold-start-path paragraph
named 50,704 (the distinct-embedding count) as the catalog size (which
is 51,282). **Fix commit** `94ddf64`.

**DOC-FALLBACK-SCOPE-52** — architecture.md said the API "requires the
artifact bundle and Redis" (optional; startup does not gate on
it) and that "a failure inside retrieval, ranking or reranking falls
back to training-set popularity" (only a Redis, two-tower or Faiss
dependency failure does; an unexpected ranking, feature-construction or
reranking error propagates as a real error instead). **Fix commit**
`94ddf64`.

**DOC-COLDSTART-STALE-53** — replay-evaluation.md and ablations.md
described a cold user's request as querying Faiss with a zero vector
and receiving "an identical, entirely generic retrieval result" --
superseded by the global-popularity cold-start path
(`docs/operations/serving-fallback.md`). Rewritten to describe current
behaviour, and the replay/ablation measurements were rerun under the
corrected sampling from DOC-SAMPLING-PROVENANCE-47 rather than patching
stale prose around unchanged numbers. **Fix commits** `d6a2247`
(reproducible coverage-check script), `9e2d4eb` (docs updated to the
rerun's real numbers: 93.6% durable-absent of 497 sampled users, 100%
Redis-absent, 0.0 hit rate unchanged under the new sample).

**DOC-PROFILING-STALE-54** — profile-hotspots.md listed a persisted,
on-disk Faiss index `ServingContext` no longer loads (it is rebuilt in
memory at every startup) and a 515 MB memory figure optimization.md
already measured down to 448.1 MB; load-test.md's own throughput table
is the "before" figure optimization.md cites as improved 26% by the
same fix. Both now carry an explicit historical notice pointing to the
documents with current numbers. **Fix commit** `94ddf64`.

**DOC-REVIEW-STATUS-55** — this entry. The three findings above sat at
"pending independent check" with no check ever recorded against them,
and prose referred to "audit findings" despite this being a
maintainer-led review throughout. **Fix commit** `9e2d4eb` (this file).

**DOC-GRAMMAR-GUARD-56** — two paragraph openings left lowercase
("measured, not estimated", "the online feature store's cold-start
handling"), and the lowercase-opening guard checked only a document's
first paragraph and headings, so a break deeper in a document was
invisible to it. Both fixed; the guard now checks every paragraph,
verified against the whole corpus (zero hits) before enabling.
**Fix commit** `94ddf64`.

**SOURCE-VOCABULARY-57** — the Markdown vocabulary guard has no reach
into `.py` files. Numbered construction-sequence labels (including
their possessive form) and tutorial-style wording persisted in thirteen
source files' comments, docstrings and experiment-log notes, replaced
with the component each one actually named. A targeted guard now
checks every `.py` file under `src/` and `tests/` for the same two
patterns, deliberately not extending the ban to the identifier that
names a single unit of iterative progress -- legitimate in code (a call
that advances an optimizer by one iteration, a per-batch training
counter, and a CI configuration key that groups a job's sequential
actions) far more often than it is construction-sequence narration
there.
**Fix commit** `3342aa3` closed the numbered form. A corrective
follow-up in PR #5, based on the merged PR #4 state, closed four
remaining occurrences the initial sweep missed
(`src/recommender/explanation/retrieval.py`,
`src/recommender/explanation/contract.py`,
`src/recommender/serving/pipeline.py`,
`src/recommender/streaming/replay_producer.py`), removed this section's
own inline-code-span wording for the same vocabulary, and strengthened
the guard to catch a bare construction-sequence reference with no
number attached -- the exact shape that had let those four slip
through.

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
| LIMIT-SAMPLING-UNCERTAINTY-44 | Sampling error of the published figures is unquantified |
| LIMIT-HOUR-OF-DAY-TIMEZONE-45 | `hour_of_day` means a different zone offline and online |

---

## Status summary

All twelve published reports are generated from a clean source commit and
record it, together with a verified-clean working tree. The tuning
comparisons ran against the leakage-free fit-half feature table
(`tune_fold_leakage: false`), and the report identifies that bundle by
full SHA-256 rather than asserting the property.

The generating source commit is recorded inside each report's
`provenance.source_commit`, which is the authoritative value; quoting it
here as well has twice gone stale after a republication, so it is not
repeated.

**Current CI status:**
[![CI](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml)

The badge is the authority for current status, deliberately. Naming a
"most recent" run in prose goes stale on the next commit -- this
document has already said that of three different runs -- so specific
run numbers appear here only where they are evidence for a *particular*
fix, and stay attached to that fix.

Run 33004519430 at commit `37e6510` is the **report-republication run**:
the run that verified the machine-readable reports published as of that
commit -- a much smaller `reports/` directory than today's twelve. It is
cited for that historical verification and nothing else. (Run 32975126661
verified the previous set, superseded when the strict content-artifact
schema changed the artifact hashes those reports recorded.)

The four jobs are `lint-and-test`, `locked-install-test`,
`api-container-test` and `integration-smoke-test`. Their being green is
worth stating because it had not been true
for the three preceding commits: the path-anchoring fix for
MANIFEST-PATHS-11 broke artifact resolution inside the container, and
the container job caught it after the change had already shipped.

A later review of the published state found two further provenance
gaps -- nested definition enforcement and the `"absent"` fit-only hash
-- both recorded under EVAL-PROVENANCE-01 above and closed in `1251fb4`.

**An earlier review of that state reopened four findings and
reclassified one**,
and the summary above it was wrong to claim fourteen closures. The reopened items are recorded
in place: EVAL-PROVENANCE-01 (fit-only artifacts unrecorded; validation
not recursive), EVAL-RETRIEVAL-LEAKAGE-09 (fit-only bundle never
validated), ARTIFACT-BUNDLE-06 (a missing manifest was accepted
alongside present artifacts), FEATURE-FRESHNESS-13 (`snapshot_id` was
neither stable across processes nor derived from content), and
FEATURE-TIMEZONE-20 (reclassified as an accepted limitation, since one
shared function prevents derivation drift but does not reconcile two
different clocks).

Two CI checks were added in response, both against real infrastructure
rather than stand-ins: the atomic claim-and-apply Lua script is now
exercised through real Redis `EVAL`, and AOF durability is demonstrated
by `docker kill` (SIGKILL) rather than a graceful stop that would pass
even with AOF disabled. Both pass on GitHub's runners, not only locally.

Three CI runs were needed to get there, and each failure was caused by
one of these changes rather than by flakiness:

- The fail-closed bundle rule rejected the container's synthetic
  artifacts, because the synthetic generator never wrote a manifest --
  the rule working correctly against a generator that had not caught up
  with it.
- Describing a tuning sample loaded the training split unconditionally,
  which made three tests that had always run on synthetic frames require
  the licensed dataset.
- `tempfile.mkstemp` creates 0600, so the manifest alone arrived
  unreadable to the unprivileged user that serves it, while every model
  and parquet beside it loaded fine.

None was fixed by weakening a check.

### How to read the counts

The headline tally counts the **34 primary findings** in this register
(`EVAL-*`, `STREAM-*`, `ARTIFACT-*`, `MANIFEST-*`, `FEATURE-*`,
`SUPPLY-*`, `API-*`, `SCHEMA-*`, `REPRO-*`, `REDIS-*`, `DEPLOYMENT-*`,
`DATA-PATH-*`, `TIMESTAMP-*`, `BANDIT-*`, `HTTP-METRICS-*`, `UNKNOWN-*`,
`CI-*`) and nothing else -- 23 from the original review, 11 more from
the follow-up verification round above.

`DOC-*` and `TEST-*` findings are tracked in their own table above.
`LIMIT-*` and `HIST-*` entries are **not findings at all** -- they are
the separate limitations register, recording disclosed properties of the
project that no fix is planned for. Counting them alongside findings
would make "accepted limitation" ambiguous between "a finding we chose
not to fix" and "a documented characteristic".

### Partially closed by scope

One primary finding is partially closed by an explicit scope decision:

- **STREAM-COMMIT-04** — commit-failure behaviour is tested against a
  fake broker, not a real one. The retry-and-stop control flow is
  covered by regression tests, and real Kafka produce/consume is smoke
  tested in CI, but no test injects a deterministic broker commit
  failure and confirms offset behaviour across a restart.

  **Accepted for this project's scope**, deliberately. A deterministic
  real-Kafka commit-failure test needs network fault injection against a
  live broker, which adds substantial CI complexity and a realistic
  chance of flakiness -- and a flaky reliability test is worse than a
  documented gap, because it trains everyone to ignore a red build.
  Revisit only if the project is meant to showcase production Kafka
  reliability specifically.

Separately, in the limitations register: **LIMIT-SAMPLING-UNCERTAINTY-44**
— sampling is representative, seeded and recorded, but variance across
seeds is not measured for the routine tuning comparisons, so those
figures' sampling error is unquantified.

**Resolved for the minimum-fresh decision specifically.** That question
was rerun as a prospectively specified experiment over the complete
tuning fold with user-clustered bootstrap intervals
(`docs/experiments/min-fresh-experiment-protocol.md`,
`reports/min-fresh-experiment.json`).

The outcome is a **non-inferiority result with boundary selection**: every
quota from 1 to 5 cleared both retention floors on held-out clicks, so
the rule -- which had no benefit, satisfiability or diversity requirement
-- selected the largest value tested. It establishes no measurable
logged-click relevance loss up to quota 5 under the frozen
candidate-list protocol; it does not establish that quota 5 is optimal
or valuable to users. The deployed quota remains 2 as an explicit
conservative product-policy override.

The same methodological concern still applies to the diversity-cap
comparison, which continues to rank by predicted relevance. **A
held-out rerun of that comparison was considered and declined**: the
basis for the cap's selection is disclosed rather than hidden, so a
rerun would be a separate research question rather than remediation, and
no untouched final split remains to validate it against. Revisit only if
diversity-policy selection becomes a central claim of the project.

Retrieval depth is not affected: it already uses clicked-item
containment and a latency budget.

Accepted limitations are listed above and are not counted as closed.

This project is **not** in a state where all review findings are closed.

## Review status

A documentation review on 2026-08-26 reopened
DOC-RERANK-CONTRADICTION-24, DOC-RETRIEVAL-SUPERSEDED-25 and
DOC-UNTOUCHED-TERM-26, which had been marked closed on incomplete
evidence, and raised further documentation findings covering stale
metric tables, stale architecture and serving-contract text, an
unrenamed explanation metric, and overstated reproducibility and CI
claims. A subsequent maintainer-led review, read-only against the
merged state, verified all three of the reopened findings as addressed
(`80fbf52`) -- not an independent or third-party check, the same
maintainer re-verifying their own fix.

That same review found eleven further findings
(DOC-SAMPLING-PROVENANCE-47 through SOURCE-VOCABULARY-57 above),
covering false sampling-provenance claims in the explanation and latency reports, a
stale metric definition, a retrieval-improvement overclaim, a frozen-
evaluation-vs-deployed-depth conflation, two numeric errors, an
overbroad dependency-fallback description, a superseded cold-start
explanation, two files presenting pre-optimization measurements as
current, this section's own stale status wording, and construction-era
vocabulary in source code with no documentation guard reaching it. All
eleven are verified closed, each against its own fix commit recorded
above -- including two evaluations rerun from a clean commit under
corrected sampling and republished, not just reworded around unchanged
numbers.

STREAM-COMMIT-04 remains partially closed by an explicit scope decision.

The twelve headline evaluation result families listed in `docs/evaluation.md` each have a committed, provenance-valid machine-readable report. No report was backfilled with inferred or false provenance. Other historical and operational measurements throughout the documentation are real but are not part of this twelve-report contract; each states its own verification scope in the document it appears in.

Of 23 primary findings: 20 verified closed, 1 partially closed by scope,
2 accepted limitations. The minimum-fresh quota is retained at 2 as a
transparent product-policy override rather than a data-selected value.

This was a **maintainer-led engineering review**, not an independent
audit. Every correction above is paired with the evidence that motivated
it, a regression test, and a statement of what the fix does not cover.
Several were defects in claims rather than in code -- a version
identifier whose documentation promised properties it did not deliver, a
validator that accepted undefined nested metrics, a migration tool that
could bless an artifact the bundle check had just refused, and CI
reported as green from local runs while it was red. Those are recorded
in place rather than summarised away, because a register that lists only
the tidy findings is less useful than one that shows what actually went
wrong.

## Follow-up verification round (2026-08-27)

A further verification pass found and fixed eleven more findings,
recorded above under "Follow-up findings" -- one critical (evaluation
provenance trusted a manifest-only environment variable ahead of the
real Git commit), two high (an orchestration script silently ran 5 of
12 published evaluations; a streaming consumer's per-user state was
still unbounded after an earlier pass had bounded everything else), five
medium, and three low. All eleven fixes were verified against real CI
(`PR #6`, run 33134350323, all four jobs green) and merged.

**A further external review of that merged state found three of the
eleven fixes were themselves incomplete**: `REDIS-DEGRADED-PATH-61`'s
circuit breaker allowed a thundering herd of probes past cooldown
instead of exactly one (no lock, no memory of an in-flight probe);
`TIMESTAMP-CONTRACT-64`'s validator still accepted several real ISO
8601 forms RFC3339's own grammar excludes; `DEPLOYMENT-CONTRACT-62`'s
build script warned on a dirty tree and built anyway. Each is recorded
in place on its own entry above with its own reproduction, fix commit,
and regression test, rather than editing the earlier account of what
`PR #6` shipped -- this register does not rewrite a prior finding's
history when a later review reopens it, the same discipline
EVAL-PROVENANCE-01's own account already establishes. New fix commits
for all three are on this branch; they stay `open` until this branch
has its own green CI run, not asserted from local runs, and this
section will be revised again once that lands.

The other eight findings from this round were not affected by the
three reopened gaps and are marked verified closed above, against the
same `PR #6` CI run.

Combined with the 23 primary findings from the original review above,
this project has now had 34 findings raised across two review rounds
by the same maintainer both times -- 31 verified closed, 3 reopened
and pending this branch's CI. This project is **still not** in a state
where all review findings are closed: nothing about closing most of
these findings establishes that a further pass would not find others,
and three of this very round's own fixes were themselves gaps an
*earlier* pass in the same round had reported as complete.

