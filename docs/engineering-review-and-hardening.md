# Engineering Review and Hardening

## 1. Purpose

This document records a maintainer-led engineering review and hardening
pass. The review examined serving correctness, temporal evaluation
integrity, reproducibility, dependency management, streaming
reliability and operational observability.

It is not a third-party or independent audit, and nothing here is
certified by anyone outside this project. What it is: a record of what
was examined, what changed, what was verified and how, and which
limitations remain open.

## 2. Scope and baseline

| | |
|---|---|
| **Baseline commit** | `cd8a4d776ad81b47313e2761e2ba9c3918293c26` |
| **Review period** | 2026-08-24 to 2026-08-25 |
| **Environments** | Windows 11 (development), `python:3.11-slim` containers (clean-environment checks), Ubuntu GitHub Actions (CI) |

**Components examined**: the serving request path, the offline and
serving-path evaluation harnesses, the retrieval and ranking model
artifacts, the streaming consumer and replay producer, dependency
resolution and packaging, the container image, and the documentation
set.

**Explicit exclusions**:

- The MIND dataset is licensed and is not distributed in this
  repository, so no recommendation-quality number here can be
  reproduced from a public clone without supplying the dataset locally.
- Public CI verifies wiring against synthetic artifacts. It does not
  reproduce any published quality metric.
- No production deployment exists. Nothing here is a statement about
  behaviour under real traffic, real concurrency or real infrastructure
  latency.

## 3. Review methodology

- **Static source review** across the serving path, evaluation
  harnesses and streaming components.
- **Clean-environment installation**: a `python:3.11-slim` container
  with no `data/` directory, installing only from the hash-verified
  lock, to reproduce what a public clone actually receives.
- **Unit and integration tests**, including fail-then-pass verification
  for regression tests: each was run against the unfixed code to
  confirm it actually catches the defect it describes.
- **Temporal-leakage analysis** of the serving-path evaluation,
  including a prefix-invariance check.
- **Adversarial explanation testing** against the wording-acceptance
  gate.
- **Kafka/Redis restart and redelivery testing**.
- **Container smoke tests** against the real built image.
- **Dependency and security scanning** (`pip-audit`, `bandit`, `ruff`).
- **Documentation consistency review** across the whole repository, not
  only this document.

## 4. Hardening summary

| Area | Engineering improvement | Verification |
|---|---|---|
| Retrieval quality | Per-article content features in the item tower, ending the 284-distinct-vector collapse; retrieval depth raised on tuning-fold evidence | Retrieval and end-to-end evaluations re-run on real data |
| Evaluation integrity | Chronological ordering with a deterministic secondary key, timestamp-group barrier, reconciled point-in-time state, tuning-fold separation | Prefix-invariance, equal-timestamp and out-of-order tests |
| Explanation safety | Structured facts, approved templates, validated substitution; generative rewriting opt-in and off by default | Adversarial tests demonstrating the lexical gate's limits |
| Reproducibility | Persisted, validated content transform; Linux CPU-only hash-verified lock; container installs that lock | Clean-container install, `pip check`, suite from a no-data clone |
| Streaming | User-keyed events, atomic event claims, deterministic replay ids | Restart, redelivery and repeated-replay tests |
| Serving | Narrow dependency fallbacks, request-id correlation on failure paths, honest cold-start labelling | API failure-path and cold-start tests |
| Security | Non-root container, digest-pinned base, blocking dependency audit | CI container and audit jobs |
| Observability | Complete serving-artifact manifest with lock digest and source commit | Per-field version-change tests |

## 5. Verification evidence

The CI status and software-verification statements in this section come
from the linked GitHub Actions run for the published commit, not from a
local machine. The licensed-data quality metrics in Section 6 come from
the committed machine-readable reports under `reports/` and are **not**
reproduced by public CI, which runs against synthetic artifacts only.

- **CI**: [GitHub Actions](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml) — the badge in `README.md` reflects current status.
- **Test counts and coverage**: reported by the `lint-and-test` job.
  Deliberately not transcribed into prose here, because a hardcoded
  count goes stale on the next commit and then quietly misreports.
- **Ruff**: passes.
- **Bandit**: no medium- or high-severity findings, which is what the
  `lint-and-test` job enforces (`bandit -ll`). Low-severity findings
  remain and were reviewed by category — see below. The count is
  deliberately not transcribed here, for the same reason the test counts
  above are not: it changes with every commit that adds a `subprocess`
  import, and a stale number in prose misreports with more authority
  than no number at all. An earlier version of this document said "six"
  and was wrong within a few commits.
- **pip-audit**: runs as a blocking CI step against the hash-verified
  lock. See the caveat below regarding `torch`.
- **Container test**: the `api-container-test` job builds the real
  image, waits on its health check, asserts a non-root user, and makes
  live requests including a `/recommend` call checked for an
  `X-Request-ID` header and a malformed request checked for a clean 422.
- **Integration test**: the `integration-smoke-test` job runs real
  Kafka produce/consume and Redis read/write round trips.
- **Machine-readable evaluation reports**: `reports/*.json`, each
  carrying the source commit, artifact hashes, configuration, seeds,
  denominators, metric definitions and limitations.

### Bandit low-severity findings

| ID | Location | Assessment |
|---|---|---|
| B105 | `data/schema.py`, `evaluation/publish.py` | False positives — Bandit matches identifiers containing "pass". One is a regex for a MIND impression token (`<news_id>-<0\|1>`); the other is the metric key `lexical_policy_pass_rate`. Neither is a credential. |
| B404, B603, B607 | `monitoring/artifact_manifest.py`, `tracking/experiment_log.py`, `evaluation/reports.py` | Real category, low risk. Each calls `git` with a fully static argument list and no user input, to record the commit a result came from. Left unsuppressed rather than silenced, since the category is legitimate even where these instances are safe. |

### pip-audit caveat

`pip-audit` reports no known vulnerabilities, but it **skips `torch`**:

```
torch  Dependency not found on PyPI and could not be audited: torch (2.13.0+cpu)
```

The CPU-only wheel comes from PyTorch's own index and carries a local
version identifier that has no PyPI entry, so the advisory database
cannot be queried for it. This is a real consequence of the CPU-only
choice: the largest dependency in the tree is version-pinned and
hash-verified but not advisory-scanned. It is recorded here rather than
left implicit in a "no known vulnerabilities" line.

## 6. Evaluation results

Results are separated by what they can support. They are not
interchangeable and should not be read as one table.

### Post-selection development evaluation

Measured on `validation`. The content-aware item tower and the
retrieval-depth change were both developed after observing behaviour on
this split, so these are development evidence, **not** untouched final
generalization estimates.

| Measurement | Before | After |
|---|---|---|
| Retrieval hit rate@100 (30,270 impressions, full 51,282-item catalog) | 0.0044 | **0.0336** |
| Distinct catalog embeddings | 284 | **50,704** |
| End-to-end retrieval-contained-click rate, 1,000-candidate pool (5,000 impressions) | 0.002 | **0.1414** |
| End-to-end hit rate@10 | 0.0005 | **0.0084** |
| End-to-end MRR | 0.000125 | **0.0048** |

Protocol: K=10, frozen evaluation contract (`docs/evaluation-protocol.md`).
Full metric definitions and denominators: `reports/`.

### Tuning-fold evaluation

Diversity cap, freshness threshold, minimum-fresh quota and retrieval
depth were compared against alternatives on a fold carved from `train`,
never on `validation` (`docs/evaluation-integrity.md`).

These comparisons are now run against a feature table built from a
retrieval model trained on the fit half alone
(`recommender.retrieval.train_fit_only`). Previously the ranking model
was refit on the fit half but `retrieval_score` came from a retrieval
model trained on all of `train`, tuning fold included — the fold was
held out from one model and not the other. The published report records
which feature table produced it (`tune_fold_leakage: false`), so a run
that fell back to the leaked table cannot be mistaken for a clean one.

**One decision is more conservative than its own evidence selects.**
The minimum-fresh quota is configured at 2. The selection rule — the
largest quota whose mean slate relevance stays within a given budget of
the unconstrained slate — chooses 5 at the 0.90 and 0.95 budgets and 3
at 0.99, so `budgets_supporting_current_configuration` is empty.

Stated precisely: **none of the three reported budgets selects 2.** That
is narrower than "no budget supports 2", which an earlier version of
this document claimed and which the data do not establish. Only three
budgets were tested. Measured relevance retention relative to an
unconstrained slate is approximately 100.02% at quota 2, 99.876% at
quota 3 and 98.919% at quota 5, so a budget of 99.9% or 100% would
select 2. The rule's output depends on where the budget is drawn, and
the budgets tried simply do not go that high.

Three further reasons the table does not settle the question:

- The comparison ranks by **predicted score**, not by held-out hit rate
  or NDCG. It measures what the model thinks, not what users did.
- The gap between quota 2 and quota 3 is about **0.15%** of predicted
  relevance, measured on a single 1,500-impression sample whose sampling
  error is unquantified (`LIMIT-SAMPLING-UNCERTAINTY-44`).
- Freshness swaps do not reapply the diversity cap, so raising the quota
  also perturbs diversity behaviour, which this comparison does not
  isolate.

The deployed value stays at 2 as a documented conservative product
judgment. Changing it would require a budget declared **before** the
run, evaluation across several seeds or the full tuning fold, and paired
confidence intervals on hit rate@10, NDCG@10, mean model score, fresh
items per slate, quota satisfaction and post-freshness distinct
categories. The diversity cap, by contrast, is configured at 3 and is
selected by the 0.90 budget.

### Untouched final evaluation

**None available.** No split remains that has not informed a design
decision. This is stated rather than worked around: the original
`validation` split informed some design decisions, and subsequent
tuning-fold experiments reduce leakage risk but do not retroactively
convert post-selection validation results into an untouched final
estimate. A genuinely untouched test split would need to be carved and
reserved before any future claim of final generalization performance.

### Synthetic CI verification

The `api-container-test` job exercises the real container against
generated artifacts. It verifies wiring only — the synthetic model's
scores are meaningless and no published number derives from them.

## 7. Remaining limitations

These are understood engineering boundaries and future work, not
concealed failures.

- **Recommendation quality remains low.** End-to-end hit rate@10 is
  approximately 0.84%. This is a production-oriented reference
  implementation with measured limitations, not a competitive
  recommender.
- **Retrieval is the primary ceiling.** The clicked item reaches the
  ranker in about 14% of impressions, so no ranking or reranking work
  can lift the end-to-end result past that.
- **Cold-start recommendations are global popularity.** Every user
  without features receives the same slate. This is deliberate;
  fabricating per-user variation would be worse than an honest global
  fallback.
- **Chronological splits confound time with user composition**, so the
  recency-leakage explanation for the popularity-feature result is
  supported but not isolated.
- **Several parameter choices rest on judgment budgets**, not on rules
  the data can settle — the diversity relevance budget, the
  minimum-fresh budget, and retrieval depth, whose predefined latency
  budget did not bind at any depth tried.
- **The deployed minimum-fresh quota (2) is not selected by any of the
  three budgets tested** (see above). It is a deliberately conservative
  choice, not a measured one; a stricter relevance budget would select
  it, and none was tried.
- **Public CI cannot reproduce licensed-data quality metrics.**
- **Kafka idempotency is bounded by claim retention** (24 hours) and
  covers the recent-feature state write, not arbitrary side effects.
- **`torch` is not advisory-scanned** (see the pip-audit caveat above).
- **A lexical policy check is not a semantic guarantee.** The
  explanation gate verifies vocabulary, not meaning; this is why the
  factual relationship is produced deterministically.
- **Development-set results are not untouched final estimates.**

## 8. Related records

- `CHANGELOG.md` — user-visible and architectural changes.
- `reports/` — machine-readable evaluation results with provenance.
- `docs/evaluation-integrity.md` — tuning-fold methodology, including
  two selection rules that failed and how they were replaced.
- `docs/retrieval-evaluation.md`, `docs/serving-path-end-to-end-evaluation.md`
  — current measurements in context.
