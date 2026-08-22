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
frozen research protocol, with every claim below traced to a specific
report or test in this repository. `docs/research-scenario.md` defines
the five research questions this project set out to answer;
`docs/conclusions.md` answers all five from the evidence gathered
across every phase.

## Real, verified results

Same frozen K=10 protocol, 30,270 validation impressions throughout
(`docs/evaluation-protocol.md`):

| Stage | Hit rate@10 | NDCG@10 |
|---|---|---|
| Best non-learned baseline (content similarity) | 0.6557 | 0.3526 |
| + Learned retrieval score as sort key | 0.6603 | 0.3446 |
| + Learned ranking model | **0.6800** | **0.3670** |
| + Diversity/freshness reranking | 0.6678 | 0.3620 |

The learned ranking model is the clearest, largest gain in the
pipeline; reranking trades a small amount of relevance for a real,
measured diversity and freshness improvement (mean distinct categories
per slate +18.3%, slates below the freshness quota −64% relative,
`docs/reranking-evaluation.md`). Retrieval alone was diagnosed as weak
in isolation — traced to a specific, quantified limitation in the
current item representation, not treated as an unexplained result
(`docs/retrieval-evaluation.md`, `docs/faiss-index.md`).

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
recommendation already made, with a real evidence-faithfulness
guarantee (`docs/explanation-boundary.md`).

## Real infrastructure, not simulated in isolation

Kafka, Redis, and a containerized recommendation API are exercised for
real in CI on every push (`docs/ci-automation.md`) — not mocked.
Failure paths (a stopped dependency, a missing model file, a restarted
container) are tested against the real running system
(`docs/restart-and-failure-testing.md`). The one thing CI does not do
is load the licensed MIND dataset itself, since it cannot be
redistributed (`docs/data-card.md`) — that verification is real, and
documented, but run locally rather than in a public CI runner.

## Getting started

Requires **Python 3.11** specifically (PyTorch, Faiss, and Transformers
here lag behind the newest CPython release) — check with `python
--version` first, or use a version manager / launcher (`py -3.11` on
Windows) if your default `python` resolves to something newer.

```bash
git clone https://github.com/MAndersonASU/real-time-recommendation-ranking-platform.git
cd real-time-recommendation-ranking-platform
py -3.11 -m venv .venv && source .venv/Scripts/activate  # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest -q            # 215 tests, no licensed data required
ruff check .
docker compose up    # starts Kafka, Redis, and the API (needs the real dataset mounted at ./data)
```

Verified end to end from a genuinely fresh clone, including a real
reproducibility bug this exact check found and fixed:
`docs/reproducibility.md`.

## Documentation index

- **Research** — `docs/research-scenario.md` (frozen questions/scope),
  `docs/evaluation-protocol.md` (frozen metrics/split), `docs/conclusions.md`
  (final answers), `docs/limitations.md`, `docs/ablations.md`,
  `docs/failure-analysis.md`
- **Data** — `docs/data-card.md`, `docs/dataset-source.md`,
  `docs/data-quality.md`, `docs/splits.md`
- **Modeling** — `docs/retrieval-model.md`, `docs/ranking-model.md`,
  `docs/reranking-diversity.md`, `docs/reranking-freshness.md`
- **Streaming & serving** — `docs/event-schema.md`, `docs/kafka-local.md`,
  `docs/online-features.md`, `docs/inference-path.md`,
  `docs/serving-fallback.md`
- **Operations** — `docs/containerization.md`, `docs/health-checks.md`,
  `docs/operational-metrics.md`, `docs/dashboard.md`,
  `docs/structured-logging.md`
- **Explanation layer** — `docs/explanation-boundary.md`,
  `docs/explanation-retrieval.md`, `docs/explanation-generation.md`,
  `docs/explanation-evaluation.md`
- **Architecture** — `docs/architecture.md` (system design, module
  ownership, and every real design decision with its reasoning)
- **Demonstration & reproducibility** — `docs/professional-demonstration.md`,
  `docs/reproducibility.md`

## License

MIT — see [`LICENSE`](LICENSE). The MIND dataset itself is governed by
Microsoft's own research license, not this project's — see
`docs/data-card.md`.
