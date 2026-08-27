# Data Card: Microsoft News Dataset (MIND)

A single, standard-structure reference for the one dataset this
project uses. Every fact below was validated against the downloaded files and cited license text against real
data or the license text at the time it was first documented — this
card consolidates those findings rather than restating them, and links
to the original source for full detail.

## Motivation

MIND was created by Microsoft to support news recommendation research
(Wu et al., ACL 2020). This project uses it as the sole real-world data
source for every offline and streaming-replay experiment — no
synthetic data stands in for it anywhere real evaluation numbers are
reported.

## Composition

- **MIND-small** (development, used throughout data ingestion through replay evaluation, 11–14):
  news catalog with title/abstract/category/subcategory/entity
  annotations, and user impression logs with click labels.
- **MIND-large** (used only for the scale and performance work's explicitly scoped scale
  testing): the official larger release of the same schema — full
 detail and measured scaling factors: `docs/experiments/mind-large.md`.
- **Real splits** (`docs/experiments/splits.md`): `train` (126,695 rows,
  2019-11-09 to 2019-11-13), `validation` (30,270 rows, 2019-11-14),
  `replay` (73,152 rows, 2019-11-15, MIND's own official dev window,
 used for streaming replay and replay evaluation; no longer untouched). Split
  boundaries are time-ordered, never randomly shuffled, and a leakage
  assertion is enforced and tested.
- **measured properties** (`docs/experiments/data-quality.md`): overall CTR
  ~4.04–4.06%; only 39.6% (train) / 12.7% (dev) of catalog articles
  ever receive an impression in a given window; `news` and `sports`
  alone make up 59.1% of the catalog; user history is null on ~2–3% of
  rows (a genuine cold-start signal, not missing data to impute).

## Collection process

Real user interaction logs collected by Microsoft News' own,
already-deployed recommender system — not a controlled experiment. This
has a direct, disclosed methodological consequence
(`docs/limitations.md`, "Selection bias in the underlying data"): every
offline metric in this project measures agreement with that system's
past choices, not unconditional relevance, since a user could only ever
click an article the original system chose to show them.

## Preprocessing / uses in this project

Ingested via `src/recommender/data/mind.py` with an explicit, tested
schema (`src/recommender/data/schema.py`); a self-consistency SHA-256 is
computed at ingestion since Microsoft publishes no official checksum
for the original files (the Hugging Face mirror's own `X-Linked-ETag`
is used instead — see License below). Used for: baseline evaluation,
embedding retrieval training, ranking model training, reranking policy
tuning, streaming replay, and every number in
`docs/conclusions.md`. Never used to train or evaluate anything outside
the frozen research scope in `docs/research-scenario.md`.

## Distribution and license

Governed by the **Microsoft Research License Terms** (full review:
`docs/dataset-source.md`) — non-commercial research use only,
**redistribution of the dataset itself is explicitly prohibited**, as
is including any material portion of it in a publication. This
project's own source-separation rule follows directly from that term:
the raw and validated MIND files are never committed to this
repository, gitignored at every stage, and CI never downloads or
touches them — every CI-verified test uses small synthetic fixtures
instead (`docs/operations/ci-automation.md`). Canonical source, real SHA-256
checksums for the files this project actually ingested, and the full
license text review: `docs/dataset-source.md`.

## Maintenance

This project does not maintain or modify the dataset itself — it is
ingested read-only from the canonical Hugging Face mirror
(`docs/dataset-source.md`) and never altered. Updates to this data card
track changes in how this project *uses* the dataset, not changes to
the dataset itself.

## Known limitations (fully detailed in `docs/limitations.md`)

- Selection bias from the original deployed system's own past choices
  (above).
- No counterfactual outcomes are ever observable — this project cannot
  know what a user would have clicked given a different candidate set.
- Sparse per-user history (median 1–2 interactions per user in a given
  window) limits how much real personalization signal exists for most
  users.
- Near-total cold start was measured directly in this project's own
  replay-based evaluation (92.4% of a real sampled user set never
  appeared in the durable feature cache; 0% had a live Redis record at
  measurement time) — a property of how this project's online stores
  were populated for research purposes, not a claim about the dataset
  itself.
