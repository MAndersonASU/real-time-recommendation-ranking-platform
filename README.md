# Real-Time Personalized Recommendation & Ranking Platform

A complete recommendation and ranking research platform combining
offline batch machine learning with real-time event streaming,
containerized serving, operational monitoring, and an optional
grounded explanation layer — built and evaluated on the Microsoft News
Dataset (MIND).

[![CI](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml)

## What this is

A five-stage pipeline — embedding-based candidate retrieval, a learned
ranking model, diversity/freshness reranking, real-time streaming
features, and containerized serving — evaluated end to end against a
frozen research protocol. Headline numbers below are traced to a
committed report under [`reports/`](reports/) or to a test in this
repository; narrative documents carry additional detail that is not
always separately reported. `docs/research-scenario.md` defines
the five research questions this project set out to answer;
`docs/conclusions.md` answers all five from the evidence gathered
across every component.

## Measured results

Two different protocols are reported below, and the difference between
them is larger than the difference between any two rows inside either
one. Reading either number without the other will mislead.

### End to end: what the assembled system actually does

The real `/recommend` path — retrieval over the full 51,282-item
catalog, then ranking, then reranking — replayed against 5,000
chronologically ordered validation impressions with point-in-time
state (`reports/end-to-end-evaluation.json`):

| Metric | Result |
|---|---|
| Retrieval contained the click (ceiling) | 0.1414 |
| **Hit rate@10** | **0.0084** |
| NDCG@10 | 0.0042 |
| MRR | 0.0048 |

A hit rate of 0.84% means the user's real next click lands in the
ten-item slate roughly once in every 119 impressions. Retrieval is the
binding constraint: no ranking improvement can lift the result above
the 14.1% ceiling, because ranking cannot promote an item it never
received. **This is the number to judge the system by.**

### Candidate-list protocol: what the ranking model contributes

The frozen research protocol scores MIND's own supplied impression
candidate list — a few dozen items per impression, already containing
the click — to isolate ranking quality from retrieval quality
(`docs/evaluation-protocol.md`, 30,270 impressions, K=10):

| Stage | Hit rate@10 | NDCG@10 |
|---|---|---|
| Best non-learned baseline (content similarity) | 0.6557 | 0.3526 |
| + Learned retrieval score as sort key | 0.6689 | 0.3518 |
| + Learned ranking model | **0.6828** | **0.3671** |
| + Diversity/freshness reranking | 0.6675 | 0.3610 |

These figures are high because the task is easy by construction: pick
from a short list that already contains the answer. They measure
ranking, and nothing here should be read as end-to-end quality — the
section above is that. The learned ranking model is the clearest gain
within this protocol; reranking trades a small, measured amount of
relevance (−2.2% hit rate) for a diversity and freshness improvement
(mean distinct categories per slate +15.1%, slates below the freshness
quota −9.8% relative, `docs/reranking-evaluation.md`).

Retrieval was originally diagnosed as weak in isolation and traced to a
specific, quantified cause: the item tower represented every article by
category and subcategory alone, collapsing 51,282 items into 284
distinct embedding vectors. That cause has since been fixed by giving
each article a content vector from its own title and abstract —
distinct embeddings rose to 50,704 and retrieval metrics improved 7.6x
to 13.5x (`docs/retrieval-evaluation.md`). It is still not a strong
retriever in absolute terms, and `docs/serving-path-end-to-end-evaluation.md`
reports what that means for the assembled system without rounding it up.

A consolidated ablation study, a real per-user-segment failure
analysis, and the full set of open questions this evidence does and
doesn't support are in `docs/ablations.md`, `docs/failure-analysis.md`,
and `docs/conclusions.md`.

## Architecture

Offline: governed dataset → validation → Parquet/DuckDB → feature
pipeline → baselines → embedding retrieval model → Faiss candidate
index → ranking model → evaluation. Online: historical replay → Kafka
→ stream consumer → recent user features (Redis) → candidate retrieval
→ ranking → reranking → a containerized FastAPI recommendation
service, with `/metrics`, structured JSON logs, and a live dashboard.
Full detail, including every real design decision and why alternatives
(MLflow, TorchRec, a separate feature store) were evaluated and
rejected: `docs/architecture.md`.

An optional grounded explanation layer sits on top of the finished
recommendation pipeline, using a small local model
(`google/flan-t5-small`) to explain — never influence — a
recommendation already made. The layer's structural boundary (it can
only ever describe a decision already made elsewhere, never feed back
into ranking) is enforced by the request type itself
(`docs/explanation-boundary.md`). The factual relationship is stated
by one of a small set of approved templates filled from validated
values — a generative model never states it. Generative rewriting
exists but is opt-in and off by default, because the only automated
check available for generated wording is lexical, and a lexical check
cannot validate meaning (`docs/explanation-generation.md`,
`docs/explanation-evaluation.md`).

## What CI actually runs, and what's verified locally instead

CI ([`docs/ci-automation.md`](docs/ci-automation.md)) runs four jobs on
pushes to `main` and on pull requests targeting `main`:

- **Linting, static security analysis, and the full test suite** behind
  a coverage floor, installed from `pyproject.toml`'s flexible lower
  bounds.
- **The same suite from a hash-verified lock file**
  (`pip install --require-hashes`), plus a blocking `pip-audit`
  vulnerability scan of exactly those pinned versions.
- **The real containerized API**, built and started in the runner
  against synthetic artifacts, then checked for a passing health check,
  a non-root user, and correct live responses — including that a
  malformed request returns a clean 422 rather than a 500.
- **Real Kafka and Redis containers**, with actual produce/consume and
  read/write round-trips.

The API container is testable in CI because
`recommender.data.synthetic` generates a seeded stand-in for every
artifact the service loads. That verifies *wiring* — the image builds,
starts unprivileged, loads its models, and answers correctly — and
nothing about recommendation quality.

What CI does *not* do: load the licensed MIND dataset. The trained
model, Faiss index, and ranking pipeline all depend on it
(`docs/data-card.md`), and this project has never redistributed it. So
every result that depends on real data
(`docs/demonstration-guide.md`, `docs/reproducibility.md`, and
the evaluation reports) is produced locally by the maintainer and
documented here. Failure paths — a stopped dependency, a missing model
file, a restarted container — are tested the same way
(`docs/restart-and-failure-testing.md`).

## Getting started

Requires **Python 3.11** specifically (PyTorch, Faiss, and Transformers
here lag behind the newest CPython release) — check with `python --version` first, or use a version manager / launcher (`py -3.11` on
Windows) if your default `python` resolves to something newer.

There are three separate entry points, with different prerequisites.

**1. Public tests — no dataset required.**

```bash
git clone https://github.com/MAndersonASU/real-time-recommendation-ranking-platform.git
cd real-time-recommendation-ranking-platform
py -3.11 -m venv .venv
# Windows (PowerShell):   .venv\Scripts\Activate.ps1
# Windows (Git Bash):     source .venv/Scripts/activate
# macOS / Linux:          source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

**2. Containerized demonstration — synthetic artifacts, no licensed data.**

Builds the API image and starts it against generated stand-in artifacts,
the same way CI does. This verifies wiring, health checks and response
shapes; it does not reproduce any evaluation number.

> **This overwrites real artifacts.** `recommender.data.synthetic` writes
> its stand-ins to the same paths the offline build uses
> (`data/processed/mind_small/`), including `news.parquet`,
> `train.parquet`, `validation.parquet`, `item_content.npz`,
> `two_tower_model.pt` and `ranking_model.skops`. Run it only in a clone
> with no trained artifacts, or back that directory up first.

```bash
python -m recommender.data.synthetic          # seeded stand-in artifacts
docker compose up -d --build api              # API only; no Kafka/Redis needed
```

**3. Licensed-data training and serving.**

Requires a local MIND download under `./data` (see
[`docs/dataset-source.md`](docs/dataset-source.md)) and a full offline
build. A clean clone does not contain the trained retrieval model,
content vectors, catalog, ranking model or bundle manifest, so
`docker compose up` cannot serve real recommendations until those are
generated locally.

Installation and serving were verified from a clean clone using
previously generated local artifacts. Licensed-data training and
evaluation were not reproduced from download in that check — see
[`docs/reproducibility.md`](docs/reproducibility.md). For an exact, fully-pinned dependency
install instead of the flexible resolution `pyproject.toml`'s lower
bounds allow (which resolves to the latest compatible versions, not to
the lower bounds themselves),
see `requirements-lock.txt`.

## Documentation index

- **Research** — [`docs/research-scenario.md`](docs/research-scenario.md) (frozen questions/scope),
  [`docs/evaluation-protocol.md`](docs/evaluation-protocol.md) (frozen metrics/split),
  [`docs/evaluation-integrity.md`](docs/evaluation-integrity.md) (held-out evaluation leakage found and
  fixed), [`docs/serving-path-end-to-end-evaluation.md`](docs/serving-path-end-to-end-evaluation.md),
  [`docs/conclusions.md`](docs/conclusions.md) (final answers), [`docs/limitations.md`](docs/limitations.md),
  [`docs/ablations.md`](docs/ablations.md), [`docs/failure-analysis.md`](docs/failure-analysis.md)
- **Data** — [`docs/data-card.md`](docs/data-card.md), [`docs/dataset-source.md`](docs/dataset-source.md),
  [`docs/data-quality.md`](docs/data-quality.md), [`docs/splits.md`](docs/splits.md)
- **Modeling** — [`docs/retrieval-model.md`](docs/retrieval-model.md), [`docs/ranking-model.md`](docs/ranking-model.md),
  [`docs/reranking-diversity.md`](docs/reranking-diversity.md), [`docs/reranking-freshness.md`](docs/reranking-freshness.md)
- **Streaming & serving** — [`docs/event-schema.md`](docs/event-schema.md), [`docs/kafka-local.md`](docs/kafka-local.md),
  [`docs/online-features.md`](docs/online-features.md), [`docs/inference-path.md`](docs/inference-path.md),
  [`docs/serving-fallback.md`](docs/serving-fallback.md)
- **Operations** — [`docs/containerization.md`](docs/containerization.md), [`docs/health-checks.md`](docs/health-checks.md),
  [`docs/operational-metrics.md`](docs/operational-metrics.md), [`docs/dashboard.md`](docs/dashboard.md),
  [`docs/structured-logging.md`](docs/structured-logging.md)
- **Explanation layer** — [`docs/explanation-boundary.md`](docs/explanation-boundary.md),
  [`docs/explanation-retrieval.md`](docs/explanation-retrieval.md), [`docs/explanation-generation.md`](docs/explanation-generation.md),
  [`docs/explanation-evaluation.md`](docs/explanation-evaluation.md)
- **Architecture** — [`docs/architecture.md`](docs/architecture.md) (system design, module
  ownership, and every real design decision with its reasoning)
- **Demonstration & reproducibility** — [[`docs/demonstration-guide.md`](docs/demonstration-guide.md),
  [`docs/reproducibility.md`](docs/reproducibility.md), [[`docs/engineering-review-and-hardening.md`](docs/engineering-review-and-hardening.md)](docs/engineering-review-and-hardening.md)
  (review scope, methodology, and disclosed limitations), [`CHANGELOG.md`](CHANGELOG.md)
- **Machine-readable results** — [`reports/`](reports/) (one JSON per
  headline table, each with metric definitions, denominators, sampling,
  provenance and limitations)

## License

MIT — see [`LICENSE`](LICENSE). The MIND dataset itself is governed by
Microsoft's own research license, not this project's — see
[`docs/data-card.md`](docs/data-card.md).
