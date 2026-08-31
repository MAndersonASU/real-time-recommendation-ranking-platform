# Engineering review register

This is the detailed record of the maintainer-led engineering review.
Stable IDs keep each finding traceable across later verification.

This was not an independent audit. A **verified closed** status means
the correction, regression coverage, and recorded CI evidence were
checked by the maintainer. It does not mean the repository is free of
other defects.

Status meanings:

- **verified closed:** corrected and verified with the evidence shown;
- **partially closed:** improved, but a named verification gap remains;
- **accepted limitation:** deliberately retained and disclosed; and
- **open:** no verified correction yet.

Baseline for the current review round:
`86f26d002100a70cc81965a07092f0888dbe1524`.

## Current aggregate status

- **Verified closed:** 32
- **Partially closed by scope:** 1 (STREAM-COMMIT-04)
- **Accepted limitations:** 2 (ARTIFACT-TRANSFORMERS-07, FEATURE-TIMEZONE-20)
- **Open:** 0
- **Total primary findings:** 35

The register contains **35 primary findings**: 23 from the original
review, 11 from the August 27 verification, and 1 from the August 30
verification. Documentation findings and the separate limitations
inventory are not included in this total.

## EVAL-PROVENANCE-01 — Evaluation reports can carry incorrect provenance
**Severity** Critical · **Status** verified closed (third pass)
**Fix commits** `d70f1df`, `b73ce6a`, `42aed02`, `c59b199`, `efacb31`, `1251fb4`
**Reports** `d2f97be`; `63b5443` from clean source `2b91dd4`
**Tests** `tests/test_reports.py`, `tests/test_tuning_publish.py`
**CI** runs 32975126661 and 32929791225; all four jobs passed

Older reports could be generated from saved JSON and then labeled with
the current commit. Nested metric values and definitions were not fully
validated, and missing fit-only artifacts could be recorded as
`"absent"`.

Each evaluation now writes its own report while it holds the results.
Publication refuses a dirty tree. Recursive checks cover nested values
and definitions, and leakage-free reports require complete SHA-256
identifiers for the fit-only bundle. Older schema-1 reports were removed
instead of being relabeled.

## EVAL-RECONCILIATION-02 — End-to-end reconciliation mis-counts repeated clicks
**Severity** High · **Status** verified closed
**Fix commits** `1de8dff`, `ec53440`
**Reports** rerun from clean source `2b91dd4` and published in `63b5443`

Multiset subtraction could drop a genuine repeated click when the same
article also appeared in pre-window history. Reconciliation now anchors
on the user's history length at first encounter and keeps later growth.

In the 2,000-impression check, old and new logic differed on one
impression and published metrics were unchanged to four decimal places.

## STREAM-IDEMPOTENCY-03 — Duplicate and concurrent events corrupt user state
**Severity** High · **Status** verified closed
**Fix commits** `1de8dff`, `ec53440`, `125e32a`
**Tests** `recommender.features.verify_lua_idempotency` and `recommender.features.verify_lua_concurrency`
**CI** runs 32929791225 and 33004519430; real Redis `EVAL`

The older read-modify-write path could roll state back on a duplicate,
lose concurrent updates, and infer an event's type from existing state.
The Lua operation now loads current state and applies the event
atomically.

The concurrency check submits 200 events from eight clients over five
runs. Reverting to the older design loses 167 of 200 updates in the
recorded reproduction.

## STREAM-COMMIT-04 — Kafka commit failures handled too weakly
**Severity** Medium · **Status** partially closed (accepted for this project's scope)
**Fix commit** `1ddd1a1` · **Tests** `tests/test_consumer.py`

Continuing after a failed offset commit could let a later cumulative
commit skip the failed message. The consumer now retries with bounded
backoff, records the failure, and stops when the offset remains
unconfirmed.

The remaining gap is deliberate: tests use a fake broker. CI checks real
Kafka produce and consume, but does not inject repeated commit failures
and verify offset behavior across a broker restart.

## ARTIFACT-VALIDATION-05 — Content artifact validation incomplete
**Severity** High · **Status** verified closed
**Fix commits** `ccc1106`, `ec53440`, `125e32a`
**Reports** `37e6510` · **CI** run 33004519430
**Tests** `tests/test_content_artifact.py`

Validation once trusted declared dimensions, allowed missing metadata,
and hashed only matrix bytes. The strict versioned schema now requires
all metadata, checks `CONTENT_DIM`, rejects invalid arrays and IDs, and
uses a canonical digest over schema, shape, dtype, ordered IDs, and
matrix bytes.

Legacy loading is an explicit migration-only option. The serving path
does not enable it.

## ARTIFACT-MIGRATION-46 — Migration tool could bless a foreign content matrix
**Severity** High · **Status** verified closed
**Fix commits** `3b9c8d4`, receipt correction `2548f21`
**Tests** `tests/test_content_artifact_migration.py`
**CI** run 33006941509

The migration tool could replace the content matrix and then publish a
new manifest as long as the model and catalog were unchanged. It could
also overwrite the original before verification finished.

Migration now validates the original bundle, writes a temporary
artifact, compares ordered IDs and matrix values with a semantic digest,
publishes only after verification, and restores the original on any
failure. The receipt records both the old and newly published manifest
hashes.

## ARTIFACT-BUNDLE-06 — Model and content artifacts are not one atomic bundle
**Severity** High · **Status** verified closed (narrowed scope)
**Fix commits** `5a3ea8e`, `efacb31` · **Tests** `tests/test_bundle.py`

A content artifact from one training run could be paired with a model
from another. A manifest now records the model, content, and catalog
hashes plus dimensions and item count. Serving rejects missing or
mismatched manifests whenever any covered artifact exists.

The manifest write is atomic, but the repository does not publish a
whole versioned directory through an atomic active-bundle pointer. That
stronger live-deployment design remains outside scope.

## ARTIFACT-TRANSFORMERS-07 — Fitted transformers unavailable for new articles
**Severity** Medium · **Status** accepted limitation

The fixed catalog has stored content vectors, but the fitted TF-IDF and
SVD transformers are not retained. A genuinely new article cannot enter
content-aware retrieval without refitting. The project has no online
article-onboarding path, so this remains an explicit fixed-catalog
boundary.

## EVAL-SPLIT-BOUNDARY-08 — Equal timestamps crossed the chronological boundary
**Severity** High · **Status** verified closed
**Fix commit** `1de8dff` · **Tests** `tests/test_tuning_fold.py`

The old row-position cut could place equal timestamps on both sides.
The split now moves an entire timestamp group together, refuses data
without a strict boundary, and reports the realized boundary and
fraction drift.

## EVAL-RETRIEVAL-LEAKAGE-09 — Tuning features leak tuning-fold labels
**Severity** High · **Status** verified closed
**Fix commits** `d70f1df`, `efacb31` · **Reports** `63b5443`
**Tests** `tests/test_fit_only_bundle.py` · **CI** run 32929791225

The ranker was fitted on the fit half, but `retrieval_score` and feature
context came from a retrieval model trained on all training rows. A
separate fit-only retrieval bundle and ranking table now use only the
fit half and are validated before loading.

The report records full bundle hashes and
`tune_fold_leakage: false`. Deployed artifacts remain separate because
the fit-only model intentionally trains on less data.

## EVAL-SAMPLING-10 — Tuning experiments use biased first-N samples
**Severity** Medium · **Status** verified closed
**Fix commits** `d70f1df`, `42aed02` · **Reports** `5f19d65`
**Tests** `tests/test_sampling.py` · **CI** run 32892449514

Using `head(...)` selected the earliest qualifying impressions and
users. Evaluations now draw seeded uniform samples without replacement
and record the eligible population, selected count, seed, time range,
user count, and digest of selected IDs.

The correction was material: end-to-end hit rate@10 changed from 0.0145
on the old prefix to 0.0084 on a representative 5,000-impression sample.
Sampling bias is closed; uncertainty across samples remains disclosed.

## MANIFEST-PATHS-11 — Manifest depends on the caller's working directory
**Severity** Medium · **Status** verified closed
**Fix commit** `efe29be` · **Tests** `tests/test_artifact_manifest.py`

Artifact paths once depended on the process directory, causing valid
files to appear absent. Paths now resolve from the repository root or
an explicit `RECOMMENDER_DATA_ROOT`.

## MANIFEST-COVERAGE-12 — Manifest omits response-affecting inputs
**Severity** Medium · **Status** verified closed
**Fix commit** `0945f55` · **Tests** `tests/test_artifact_manifest.py`

The serving version omitted behavior data used to derive popularity,
first-seen, and durable features. The manifest now fingerprints the
training and validation behavior files. Together with the source
commit, those inputs identify the deterministic derived frames.

## FEATURE-FRESHNESS-13 — Durable-feature freshness is not operational
**Severity** Medium · **Status** verified closed (scope decision)
**Fix commits** `efe29be`, `efacb31`
**Tests** `tests/test_serving_cache.py`, `tests/test_snapshot_identity.py`

Restarting once made frozen 2019 data appear newly refreshed.
`built_at` and `data_as_of` are now separate, readiness reports the real
data age, and snapshot identity hashes every published field in stable
user order.

Cross-process tests with different `PYTHONHASHSEED` values verify that
identical data keeps one ID and changed feature data changes it.
Automated atomic refresh remains outside scope.

## FEATURE-DETERMINISM-14 — Durable features nondeterministic on tied timestamps
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e` · **Tests** `tests/test_ranking_features.py`

Durable features now use stable sorting by
`("time", "impression_id")`, making the impression ID the deterministic
tiebreak for equal timestamps.

## SUPPLY-RUNTIME-LOCK-15 — Production image installs dev and audit tooling
**Severity** Medium · **Status** verified closed
**Tests** CI job `locked-install-test`

Runtime and development packages now have separate hash-pinned locks.
The production image installs only `requirements-lock.txt`. CI confirms
that development tools are absent and that the serving application
imports with only runtime packages installed.

## SUPPLY-DOCKERIGNORE-16 — No restrictive `.dockerignore`
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`

The Docker build context now excludes licensed data, local secrets, Git
metadata, virtual environments, caches, and build output. CI builds the
API image with these exclusions.

## STREAM-DURABILITY-17 — Redis may lose acknowledged writes
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`
**Tests** `recommender.features.verify_aof_recovery` with real Redis
**CI** run 32929791225

Redis now uses append-only persistence with
`appendfsync everysec`. CI kills Redis with `SIGKILL` and confirms that
user state and processed-event claims survive. A graceful shutdown was
not used because it would not test crash recovery.

## SCHEMA-EVENT-18 — Event schema validation too permissive
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e` · **Tests** `tests/test_streaming_schema.py`

Events now enforce allowed sources, bounded identifiers, a fixed field
set, and the timestamp contract. Event IDs use UUID5 over event content,
so the same input produces the same ID across producers.

## API-USERID-19 — User ids insufficiently bounded
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`
**Tests** `tests/test_user_id_unicode.py` · **CI** run 32929791225

The JSON and demonstration routes now require
`^[A-Za-z0-9._:-]{1,128}$`. This rejects empty IDs, controls, whitespace,
zero-width characters, bidirectional marks, and byte-order marks.

## FEATURE-TIMEZONE-20 — `hour_of_day` semantics differ offline vs online
**Severity** Medium · **Status** accepted limitation
**Partial fix** `0945f55` · **Tests** `tests/test_ranking_features.py`
**Tracked as** `LIMIT-HOUR-OF-DAY-TIMEZONE-45`

One shared function prevents offline and online derivation code from
drifting. It cannot reconcile the underlying clocks: MIND's timezone is
undocumented, while a live request without a historical anchor uses
UTC. Removing the feature would require retraining and reevaluation, so
the difference remains disclosed.

## SUPPLY-IMAGE-PINS-21 — Redis, Kafka and Actions use mutable tags
**Severity** Medium · **Status** verified closed
**Fix commit** `5a3ea8e`

Redis and Kafka images are pinned by digest. GitHub Actions are pinned
by commit SHA with release comments for readable upgrades.

## API-EXPOSURE-22 — API bound to all interfaces
**Severity** Medium · **Status** verified closed
**Fix commit** `ccc1106`

The API binds to `127.0.0.1` by default. `API_BIND_HOST` is required to
expose it more broadly.

## EVAL-PROVENANCE-58 — Evaluation reports could inherit a manifest env var as their commit
**Severity** Critical · **Status** verified closed
**Fix commit** `912c00a` · **Tests** `tests/test_reports.py`
**CI** PR #6, run 33134350323

`source_commit()` once trusted `GIT_COMMIT_SHA` before Git itself;
`GIT_COMMIT_SHA=banana` produced a valid report. Reports now resolve
Git HEAD directly and require a 40-character lowercase commit hash.
Full-history CI also confirms recorded commits exist and precede HEAD.

## REPRO-ORCHESTRATION-59 — `evaluate_all.sh` ran 7 of the 12 published evaluations
**Severity** High · **Status** verified closed
**Fix commit** `5dd91f9` · **Tests** `tests/test_orchestration_scripts.py`
**CI** PR #6, run 33134350323

Five evaluation modules lacked `--output-dir` support and were absent
from the orchestration script. The scripts now include every expected
evaluation, build the fit-only bundle, and detect Windows and POSIX
virtual-environment layouts. A test derives the required module set from
the report contract.

## STREAM-MEMORY-60 — `StreamConsumer.user_states` was still unbounded
**Severity** High · **Status** verified closed
**Fix commit** `97ac5e4` · **Tests** `tests/test_consumer.py`
**CI** PR #6, run 33134350323

The per-user dictionary remained unbounded after other caches were
limited. `BoundedUserStates` now evicts the least recently used entry.
The long-running syncing consumer treats this as a disposable cache over
Redis; the plain consumer is explicitly limited to finite verification
utilities.

## REDIS-DEGRADED-PATH-61 — A Redis failure fell all the way back to flat popularity
**Severity** Medium · **Status** verified closed
**Fix commits** `b992259`, `be8b5ce`, `de457c3`, `5c32706`, `efaea84`
**Tests** `tests/test_cold_start.py`, `tests/test_serving_fallback.py`, `tests/test_redis_circuit_breaker.py`, `tests/test_deployment_contract.py`
**CI** PR #9 run 33263672952; merged as `a52d04c`; main run 33266339509

Redis supplies recent clicks, so an outage should not discard durable
features and the trained model. The API now treats connectivity failure
as missing recent data, remains personalized with durable data, uses a
0.2-second no-retry connection policy, and opens a circuit breaker after
repeated failures.

Later verification corrected three breaker defects: concurrent callers
could all claim the recovery probe, some exceptions never released the
probe, and malformed stored JSON was counted as a connectivity failure.
The final design separates Redis transport success from parsing and
allows exactly one half-open probe.

## DEPLOYMENT-CONTRACT-62 — Compose blocked API startup on a Redis dependency the process doesn't have
**Severity** Medium · **Status** verified closed
**Fix commits** `be8b5ce`, `81483fd`, `9cf0852`, `1cf8464`, `208dcdd`
**Tests** `tests/test_deployment_contract.py`
**CI** PR #9 run 33263672952; merged as `a52d04c`; main run 33266339509

Compose once blocked API startup on Redis even though the application
connects lazily. That gate was removed and live testing confirmed the
API starts and serves with Redis absent.

The image build wrapper now refuses a dirty tree, anchors itself to its
repository, checks the whole tree, supplies the real Git commit, and
pins the exact Compose file and project directory. These controls
prevent another repository, `COMPOSE_FILE`, or an auto-discovered
override from changing the build unnoticed.

## DATA-PATH-CONSISTENCY-63 — `RECOMMENDER_DATA_ROOT` didn't move most of the project's own paths
**Severity** Medium · **Status** verified closed
**Fix commits** `5dd91f9`, `b992259`, `e615ff2`
**Tests** `tests/test_data_path_consistency.py` · **CI** PR #6 run 33134350323

All data constants now use `data_path()` or `mind_small_path()`.
Subprocess tests import every discovered constant from another working
directory and confirm that `RECOMMENDER_DATA_ROOT` moves it. A static
guard rejects new bare `Path("data/...")` literals.

## TIMESTAMP-CONTRACT-64 — The RFC3339 validator accepted timestamps that aren't RFC3339
**Severity** Medium · **Status** verified closed
**Fix commits** `063bbf5`, `35c01b3`, `28d578d`, `f72a556`
**Tests** `tests/test_streaming_schema.py`, `tests/test_documentation.py`
**CI** PR #9 run 33263672952; merged as `a52d04c`; main run 33266339509

Replay data uses MIND's naive dataset-local timestamps. Other sources
use a documented canonical RFC3339 profile: uppercase `T` or `Z`,
mandatory seconds, a valid numeric offset when not `Z`, and no leap
second.

Several verification rounds tightened grammar, offset ranges, and
documentation. The project explicitly says this profile is narrower
than full RFC3339, which also permits lowercase separators.

## BANDIT-REVIEW-65 — A real evaluation invariant used `assert`; the Bandit table was stale
**Severity** Medium · **Status** verified closed
**Fix commits** `e615ff2`, `7d5f2ef`
**Tests** `tests/test_recent_features_ablation.py`, `tests/test_bandit_table_sync.py`
**CI** PR #6, run 33134350323

An optimized Python run could remove the paired-sample digest assertion
and publish an unpaired comparison. The code now raises `ValueError`.
The Bandit table now lists every subprocess file, and tests compare it
with a fresh scan and reject bare assertions in production code.

## HTTP-METRICS-SCOPE-66 — `recommend_requests_total` never saw a 422 or a middleware-level 500
**Severity** Low · **Status** verified closed
**Fix commit** `b992259`
**Tests** `tests/test_app.py`, `tests/test_metrics.py`, `tests/test_dashboard.py`
**CI** PR #6, run 33134350323

`http_requests_total` now records every response in access middleware,
using the matched route template and status class. The dashboard calls
the narrower older metric “Recommend attempts” instead of “Total
requests.”

## UNKNOWN-DATA-AGE-67 — Unknown durable-feature data age reported as a false zero
**Severity** Low · **Status** verified closed
**Fix commit** `b992259` · **Tests** `tests/test_metrics.py`, `tests/test_app.py`
**CI** PR #6, run 33134350323

Unknown age once became `0.0` because both values are falsy in Python.
The gauge now uses Prometheus `NaN` for unknown age and exposes a
separate known-age gauge for simpler queries and alerts.

## CI-COVERAGE-WORDING-68 — CI's coverage comment cited a number already wrong
**Severity** Low · **Status** verified closed
**Fix commits** `912c00a`, `4547c27`
**CI** PR #6, run 33134350323

The CI comment no longer copies a coverage percentage that will become
stale. It states only the enforced `--cov-fail-under=60` floor. A
documentation guard rejects a new hardcoded “coverage is X%” comment.

## SERVING-DURABLE-HISTORY-69 — Live retrieval ignored durable history when Redis had none
**Severity** High · **Status** verified closed
**Fix commits** `3054fca`, `f5eb8ce`, `702df9d`, `e6b4cd2`, `b05dd54`
**Tests** `tests/test_pipeline.py`, `tests/test_serving_fallback.py`, `tests/test_demo.py`, `tests/test_online_features.py`, `tests/test_snapshot_identity.py`, `tests/test_serving_contract.py`, `tests/test_evaluate_durable_history_fallback.py`
**Report** [`durable-history-fallback.json`](../reports/durable-history-fallback.json)
**CI** PR #12 run 33326011615; merged as `b83a4da`; main run 33329510626

When Redis held no clicks, retrieval ignored saved durable history and
used the same global-popularity pool for returning users. Ranking flags
could still say durable features were used, which hid that retrieval
itself was not personalized.

Retrieval now chooses one source: usable recent history, otherwise
bounded durable history, otherwise global popularity. Recent and durable
histories are not merged. The response reports that source separately
from ranking-feature flags.

The direct six-user reproduction improved from 3 distinct top-10 slates
and 10 distinct items to 6 slates and 44 items. The dedicated post-fix
evaluation covered 7,790 impressions from 6,885 users and produced
7,312 distinct served slates with 15.2% catalog coverage. It was not a
paired large-scale before-and-after comparison.

Affected reports were rerun. Explanation refusal fell from 66.1% to
20.6%, and service median latency fell from 31.44 ms to 21.78 ms,
mainly because candidate retrieval fell from 13.11 ms to 0.86 ms.

## Documentation findings

These items concern wording, presentation, and supporting tests. They
are tracked separately from the 35 primary engineering findings.

| ID | Plain-language finding | Status or evidence |
|---|---|---|
| DOC-METRIC-PROMINENCE-23 | Candidate-list results were more prominent than end-to-end results | Verified closed |
| DOC-RERANK-CONTRADICTION-24 | The README and reranking page disagreed | Verified at `80fbf52` |
| DOC-RETRIEVAL-SUPERSEDED-25 | Old retrieval conclusions appeared current | Verified at `80fbf52` |
| DOC-UNTOUCHED-TERM-26 | Split wording implied unused data when none remained | Verified at `80fbf52` |
| DOC-MINFRESH-EVIDENCE-27 | The minimum-fresh comparison lacked a committed report | Verified closed |
| DOC-BANDIT-COUNTS-28 | A copied Bandit count became stale | Verified closed |
| DOC-OVERCLAIM-29 | Some claims were stronger than the implementation | Verified closed |
| DOC-SETUP-ENCODING-30 | Setup assumed POSIX activation and one file was not valid UTF-8 | Verified closed |
| DOC-LOCKGEN-31 | Lock-generation instructions were incomplete | Verified closed |
| TEST-STARLETTE-32 | A TestClient deprecation warning remains | Accepted limitation |
| TEST-SVD-WARNING-33 | A degenerate test fixture produced an SVD warning | Verified closed |
| DOC-SAMPLING-PROVENANCE-47 | Bounded evaluations used first-N samples but reported otherwise | Fixed in `0e80e42`; reports in `e368521` |
| DOC-EXPLANATION-METRIC-DEFN-48 | A metric definition kept the old name | Fixed in `0e80e42` |
| DOC-RETRIEVAL-OVERCLAIM-49 | A claim said every metric improved 7.6–13.5×, but coverage improved 1.5× | Fixed in `94ddf64` |
| DOC-N100-DEPTH-CONFLATION-50 | An N=100 evaluation was described as if it used serving depth 1,000 | Fixed in `94ddf64` |
| DOC-CATALOG-SIZE-51 | A distinct-vector count was labeled as catalog size | Fixed in `94ddf64` |
| DOC-FALLBACK-SCOPE-52 | Architecture overstated Redis and fallback requirements | Fixed in `94ddf64` |
| DOC-COLDSTART-STALE-53 | Replay and ablation pages described an older cold-start path | Fixed in `d6a2247` and `9e2d4eb` |
| DOC-PROFILING-STALE-54 | Older profile and load measurements appeared current | Fixed in `94ddf64` |
| DOC-REVIEW-STATUS-55 | Review language and closure claims were inaccurate | Fixed in `9e2d4eb` |
| DOC-GRAMMAR-GUARD-56 | A prose guard missed lowercase paragraph openings | Fixed in `94ddf64` |
| SOURCE-VOCABULARY-57 | Tutorial-style construction wording remained in source comments | Fixed in `3342aa3` and PR #5 |

## Disclosed limitations inventory

These are project properties with no current correction planned. They
are not included in the primary-finding tally.

| ID | Limitation |
|---|---|
| LIMIT-TORCH-AUDIT-34 | CPU-only PyTorch is hash-verified but not advisory-scanned |
| LIMIT-NO-FINAL-SPLIT-35 | No untouched final evaluation split remains |
| LIMIT-QUALITY-36 | Recommendation quality remains low |
| LIMIT-COLDSTART-37 | Featureless users receive one popularity slate |
| LIMIT-RECENCY-CONFOUND-38 | Recency analysis is mixed with changes in user composition |
| LIMIT-JUDGMENT-PARAMS-39 | Some settings depend on product judgment |
| LIMIT-PUBLIC-CI-40 | Public CI cannot reproduce licensed-data metrics |
| LIMIT-IDEMPOTENCY-WINDOW-41 | Idempotency lasts only as long as claim retention |
| LIMIT-LEXICAL-ONLY-42 | Lexical validation does not verify meaning |
| HIST-CI-CLAIM-43 | An older report called local checks green CI while CI was red |
| LIMIT-SAMPLING-UNCERTAINTY-44 | Routine sampled figures do not quantify sampling error |
| LIMIT-HOUR-OF-DAY-TIMEZONE-45 | Offline and online `hour_of_day` use different clock assumptions |

The minimum-fresh question has stronger evidence than the routine
sampled comparisons: the complete tuning fold and user-clustered
bootstrap bounds found no measurable logged-click relevance loss
through quota 5. The rule selected the largest tested value because it
contained no benefit requirement. The deployed quota remains 2 as a
conservative policy choice.

## Evidence notes

The CI badge is the current source of truth:
[![CI](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml).

Specific CI run numbers stay attached to the findings they verified.
Machine-readable reports carry their own authoritative
`provenance.source_commit`. The register does not repeat a single
“current report commit” because that value changes whenever reports are
republished.

Related pages:

- [Engineering review summary](engineering-review.md)
- [Review method and hardening](engineering-review-and-hardening.md)
- [Project limitations](limitations.md)
- [Evaluation index](evaluation.md)
