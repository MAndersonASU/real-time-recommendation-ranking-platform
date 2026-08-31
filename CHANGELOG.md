# Changelog

This file records user-visible, research, and architectural changes.
Measurements belong to the date shown and may have been replaced by a
later entry. Use the [evaluation index](docs/evaluation.md) for current
results.

## August 30, 2026 — Durable-history retrieval

### Changed

- Retrieval now uses a user's bounded durable history when Redis has no
  usable recent clicks. It does not merge recent and durable histories.
- `RecommendationResponse.retrieval_history_source` reports whether
  recent history, durable history, or global popularity produced the
  candidates.
- The demonstration page shows retrieval source separately from
  ranking-feature status.

### Added

- A dedicated durable-history evaluation and
  [machine-readable report](reports/durable-history-fallback.json).
- Missing entries for tuning verification and the minimum-fresh
  experiment in the evaluation index.
- A guard that requires every committed report to appear in the
  evaluation index.

### Corrected

- The README's container command now names Redis explicitly.
- End-to-end, explanation, replay, ablation, and service-latency
  evaluations were rerun where this serving correction could affect
  their results.

The behavior was found in a maintainer-led review and is tracked as
`SERVING-DURABLE-HISTORY-69`. It was not an independent audit.

## August 27, 2026 — Documentation and secret checks

- Added regression checks for duplicated words and inconsistent
  component terminology.
- Replaced broad credential keywords with checks for provider key
  formats and high-entropy values assigned to secret-like names.
- Kept SHA-256 artifact hashes out of secret alerts because the
  repository publishes those hashes intentionally.

## August 25, 2026 — Reproducibility and explanation controls

### Retrieval and artifacts

- Added article title and abstract features to the item tower. The old
  category-only representation gave 51,282 articles only 284 distinct
  vectors.
- Increased serving retrieval depth from 50 to 1,000 using tuning-fold
  evidence.
- Persisted and validated the fitted content transformation so
  training, index construction, evaluation, and serving use the same
  coordinates.
- Extended the serving manifest to cover content, model, reranking and
  retrieval settings, feature sizes, seeds, dependency lock, and source
  commit.

### Evaluation

- Enforced deterministic chronological ordering.
- Scored all impressions at one timestamp before applying any events
  from that timestamp.
- Reconciled point-in-time feature state from authoritative history.
- Published validated JSON reports with source commit, artifact hashes,
  settings, seeds, denominators, metric definitions, and limitations.
- Made the normal test suite independent of the licensed dataset.

### Explanations

- Moved factual explanation content into structured facts and approved
  templates.
- Kept optional generative rewriting off by default because lexical
  checks cannot verify meaning.
- Renamed the reported measure to lexical-policy pass rate.

### Supply chain and serving

- Split runtime and development dependency locks.
- Added hash verification and the CPU-only PyTorch index to CI and the
  container build.
- Pinned the container base by digest.
- Removed unused `httpx2` and declared `httpx` directly.
- Added deterministic replay event IDs for bounded idempotency.
- Made the demonstration explicit when a user receives global
  popularity rather than personalized retrieval.
- Added DST-boundary tests for ambiguous and nonexistent local times.

## August 24, 2026 — Engineering hardening

This entry combines two related maintenance passes from the same date.
The figures below are historical and are retained only to explain the
changes made then.

### Retrieval

- Added per-article content features. Distinct catalog embeddings
  increased from 284 to 50,704.
- Historical hit rate@100 increased from 0.0044 to 0.0336 under that
  date's retrieval protocol.
- Increased candidate depth from 50 to 1,000. On the tuning fold,
  clicked-item containment increased from 5.8% to 20.9%.
- Replaced zero-vector index queries for featureless users with an
  explicit training-popularity fallback.

### Point-in-time evaluation

- Seeded isolated state from each impression's own history instead of
  starting almost every user empty.
- Added `retrieval_contained_a_click_rate` to separate retrieval misses
  from ranking misses.
- Added chronological processing and per-impression isolated state to
  prevent future events from changing an earlier recommendation.
- Replaced selection rules that could not distinguish parameter values.

The historical 2,000-impression run changed from 0.2% to 12.2%
clicked-item containment, from 0.0005 to 0.0145 hit rate@10, and from
0.000125 to 0.0074 MRR. Later representative sampling replaced these
figures; they are not current results.

### Streaming and API

- Added atomic Redis claims so restart redelivery can repair saved
  state without applying an event twice.
- Keyed replay events by user rather than item.
- Removed raw user IDs from fallback logs.
- Narrowed successful fallback to known dependency failures. Unexpected
  ranking or feature errors now remain errors.
- Preserved request correlation in response headers and error logs.
- Standardized internal clock handling on UTC and stopped treating
  unknown item age as zero.

### Reproducibility, security, and CI

- Regenerated the dependency lock after finding that `skops` was
  missing.
- Added locked-install, dependency-audit, container, and integration
  checks to CI.
- Added a non-root container user, a health check, an exec-form
  entrypoint, and an explicit source-commit build argument.
- Replaced a single-file model version with a full serving-artifact
  manifest.
- Added a 60% coverage floor.

The first lock correction on this date was version-pinned but not yet
hash-verified. Hash verification was added in the later August 24 work
and clarified on August 25. This note resolves the apparent
contradiction between the original same-day entries.

See the [engineering review method](docs/engineering-review-and-hardening.md)
and [review register](docs/engineering-review-register.md) for
verification evidence and remaining limits.
