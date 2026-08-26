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

**Done** All four reports are generated from clean source commit
`2b91dd4` and published in commit `63b5443`, each recording that source
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
**Fix commits** `ccc1106`, `ec53440`, and the strict schema below
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

A pre-schema artifact is still verified against the weaker digest it was
actually written with, so "unverifiable" and "corrupt" stay distinct
claims.

**Existing artifacts were upgraded, not rebuilt**
(`recommender.retrieval.upgrade_content_artifact`). Rebuilding means
refitting TF-IDF and SVD, and SVD axes are defined only up to sign and
ordering, so a refit produces a different valid basis and the trained
item tower would score coordinates it has never seen. The upgrade adds
metadata only, and verifies the matrix is bit-identical before keeping
the result. Because the file bytes change, the bundle manifest is
re-fingerprinted -- under a guard narrow enough that it refuses unless
the model and catalog hashes still match, since a blanket refresh would
defeat the bundle check entirely.

**Remaining** The checksum covers matrix bytes only, not shape, dtype or
ids; artifacts predating the metadata fields are still accepted.

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
| LIMIT-SAMPLING-UNCERTAINTY-44 | Sampling error of the published figures is unquantified |
| LIMIT-HOUR-OF-DAY-TIMEZONE-45 | `hour_of_day` means a different zone offline and online |

---

## Status summary

All four published reports are generated from a clean source commit and
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

Run 32975126661 at commit `d2f97be` is the **report-republication run**:
the run that verified the four machine-readable reports currently in
`reports/`. It is cited for that and nothing else.

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

The headline tally counts the **22 primary findings** in this register
(`EVAL-*`, `STREAM-*`, `ARTIFACT-*`, `MANIFEST-*`, `FEATURE-*`,
`SUPPLY-*`, `API-*`, `SCHEMA-*`) and nothing else.

`DOC-*` and `TEST-*` findings are tracked in their own table above.
`LIMIT-*` and `HIST-*` entries are **not findings at all** -- they are
the separate limitations register, recording disclosed properties of the
project that no fix is planned for. Counting them alongside findings
would make "accepted limitation" ambiguous between "a finding we chose
not to fix" and "a documented characteristic".

### Not closed

One primary finding remains open:

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
seeds is not measured, so the published figures' sampling error is
unquantified. This matters most for the minimum-fresh comparison, where
the gap between quota 2 and quota 3 is about 0.15% of predicted
relevance on a single 1,500-impression sample.

Accepted limitations are listed above and are not counted as closed.

This project is **not** in a state where all audit findings are closed.
