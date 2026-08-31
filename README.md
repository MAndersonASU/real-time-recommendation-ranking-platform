# Real-Time Personalized Recommendation & Ranking Platform

A research platform for building, serving, and evaluating personalized
news recommendations. It combines offline model training, real-time
events, a FastAPI service, monitoring, and an optional grounded
explanation layer.

The project uses the Microsoft News Dataset (MIND). The code is public;
the licensed dataset and trained artifacts are not included.

[![CI](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/MAndersonASU/real-time-recommendation-ranking-platform/actions/workflows/ci.yml)

## Choose what you want to do

| Goal | Start here |
|---|---|
| Understand the system | [Architecture](docs/architecture.md) |
| Review measured results | [Evaluation](docs/evaluation.md) |
| Run the public test suite | [Local setup](#run-the-public-test-suite) |
| Start a containerized demonstration | [Container demonstration](#run-the-container-demonstration) |
| Reproduce licensed-data work | [Reproducibility](docs/reproducibility.md) |
| Operate the service | [Operations](docs/operations.md) |
| Review known limits | [Limitations](docs/limitations.md) |

## What the platform does

The offline path prepares data and trains the models:

```text
MIND data
  -> validation and Parquet tables
  -> user and item features
  -> two-tower retrieval model and Faiss index
  -> learned ranking model
  -> diversity and freshness reranking
  -> evaluation reports and versioned artifacts
```

The online path serves recommendations:

```text
historical and live events
  -> Kafka
  -> streaming consumer
  -> recent features in Redis
  -> retrieval
  -> ranking
  -> reranking
  -> FastAPI response
```

The service can continue without Redis. In that condition it uses
durable user features and reports the degraded dependency through
`/ready`. See [failure-safe serving](docs/operations/serving-fallback.md)
for the exact behavior.

The explanation layer describes a recommendation after selection. It
cannot influence retrieval, ranking, or reranking. Deterministic
templates provide the factual statement. Optional local-model rewriting
is disabled by default.

<details>
<summary>Where each component lives</summary>

| Area | Package |
|---|---|
| Data ingestion and validation | `recommender.data` |
| Offline and online features | `recommender.features` |
| Candidate retrieval | `recommender.retrieval` |
| Ranking | `recommender.ranking` |
| Diversity and freshness | `recommender.reranking` |
| Kafka replay and consumption | `recommender.streaming` |
| API and fallback behavior | `recommender.serving` |
| Metrics, logs, and dashboards | `recommender.monitoring` |
| Evaluation and report publication | `recommender.evaluation` |
| Grounded explanations | `recommender.explanation` |

</details>

## Results at a glance

The project reports two different evaluation protocols. They answer
different questions and should not be compared as if they were the same
test.

### End-to-end serving result

This is the result for the assembled `/recommend` path: retrieval over
the 51,282-item catalog, followed by ranking and reranking. The replay
uses 5,000 chronological validation impressions and point-in-time user
state.

| Metric | Result |
|---|---|
| Retrieval contained the click | 0.1414 |
| **Hit rate@10** | **0.0084** |
| NDCG@10 | 0.0042 |
| MRR | 0.0048 |

The clicked item appears in the final ten recommendations in about
0.84% of impressions, or roughly once in 119 impressions. Retrieval is
the main constraint: the clicked item reaches ranking in only 14.14% of
impressions.

Source: [end-to-end report](reports/end-to-end-evaluation.json) and
[plain-language interpretation](docs/experiments/serving-path-end-to-end-evaluation.md).

### Candidate-list ranking result

This protocol scores MIND's supplied candidate lists. Each list already
contains the clicked item, so this test isolates ranking quality and
does not measure full-catalog retrieval.

| Model output | Hit rate@10 | NDCG@10 |
|---|---|---|
| Content-similarity baseline | 0.6557 | 0.3526 |
| Learned retrieval score | 0.6689 | 0.3518 |
| Learned ranking model | **0.6828** | **0.3671** |
| Ranking plus diversity/freshness | 0.6675 | 0.3610 |

The ranking model improves the candidate-list result. Reranking then
trades a small amount of relevance for broader category coverage and
more fresh items.

<details>
<summary>Why the two result tables are so different</summary>

The candidate-list test starts with a short list that already contains
the correct item. The end-to-end test starts with the full catalog and
must retrieve the correct item before ranking can help. The first table
therefore measures the complete system; the second isolates the
ranker's contribution.

</details>

<details>
<summary>What changed in retrieval</summary>

The original item representation used only category and subcategory.
That reduced 51,282 articles to 284 distinct vectors. Adding title and
abstract content increased the count to 50,704 distinct vectors. The
four relevance metrics improved by 7.6x to 13.5x, while catalog coverage
improved by 1.5x. Retrieval remains the largest quality constraint.

See [retrieval evaluation](docs/experiments/retrieval-evaluation.md).

</details>

## Run the public test suite

Requirements:

- Python 3.11
- Git

Create an environment:

```bash
git clone https://github.com/MAndersonASU/real-time-recommendation-ranking-platform.git
cd real-time-recommendation-ranking-platform
python -m venv .venv
```

Activate it with the command for your shell:

- Windows PowerShell: `.venv\Scripts\Activate.ps1`
- Windows Git Bash: `source .venv/Scripts/activate`
- macOS or Linux: `source .venv/bin/activate`

Install and verify:

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

No MIND download is required for these checks.

## Run the container demonstration

This demonstration uses seeded synthetic artifacts. It verifies the
container, API contract, health checks, and Redis integration. It does
not reproduce the published recommendation-quality numbers.

> **Use a clean clone with no trained artifacts.** The synthetic-data
> command writes to `data/processed/mind_small/` and replaces files at
> the same paths used by a licensed-data build.

```bash
python -m recommender.data.synthetic
docker compose up -d --build api redis
```

Try the service:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d '{"user_id":"U1","num_candidates":5}'
```

Stop the containers:

```bash
docker compose down
```

<details>
<summary>Run the API without Redis</summary>

```bash
docker compose up -d --build api
```

The API remains available. `/ready` reports Redis as degraded, and
`/recommend` uses durable features. This is a supported fallback
condition, not a full production configuration.

</details>

## Work with the licensed dataset

Download MIND separately and place it under `./data`. Follow:

1. [Dataset source and license](docs/dataset-source.md)
2. [Data card](docs/data-card.md)
3. [Reproducibility guide](docs/reproducibility.md)
4. [Evaluation guide](docs/evaluation.md)

A clean clone does not include the trained retrieval model, content
vectors, Faiss index, ranking model, or serving manifest. Those
artifacts must be generated locally before the service can provide
real-data recommendations.

For a fully pinned install, use `requirements-lock.txt`. The regular
`pip install -e ".[dev]"` command uses the compatible version ranges
in `pyproject.toml`.

## Evidence and CI

The 13 published report families in [`reports/`](reports/) include
machine-readable metrics, definitions, denominators, sampling details,
limitations, source commits, and artifact hashes. The complete index is
in [`docs/evaluation.md`](docs/evaluation.md).

CI runs four jobs:

- linting, security analysis, tests, and coverage;
- the same suite from the hash-verified dependency lock, followed by
  `pip-audit`;
- a real API container test using synthetic artifacts;
- real Kafka and Redis integration checks.

CI does not download MIND or reproduce licensed-data results. Those
measurements are generated locally and published with provenance.

## Documentation map

| Document | Question it answers |
|---|---|
| [Architecture](docs/architecture.md) | How do the offline and online paths work? |
| [Evaluation](docs/evaluation.md) | What was measured, and under which protocol? |
| [Operations](docs/operations.md) | How is the service configured, observed, and recovered? |
| [Conclusions](docs/conclusions.md) | What does the evidence support? |
| [Limitations](docs/limitations.md) | What remains uncertain or out of scope? |
| [Engineering review](docs/engineering-review.md) | What was reviewed, and what remains limited? |
| [Research scenario](docs/research-scenario.md) | Which questions defined the work? |
| [Demonstration guide](docs/demonstration-guide.md) | How can the running service be shown? |

Detailed experiment notes are under [`docs/experiments/`](docs/experiments/).
Runtime references are under [`docs/operations/`](docs/operations/).
Superseded measurements are under [`docs/archive/`](docs/archive/).

## License

The code is available under the [MIT License](LICENSE). MIND remains
subject to Microsoft's dataset license; see the [data card](docs/data-card.md).
