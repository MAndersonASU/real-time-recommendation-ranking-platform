# Evaluation

How this project measures recommendation quality, what the numbers mean,
and where they stop being evidence. Individual experiments live under
[`docs/experiments/`](experiments/); this page is the map.

## Two protocols, deliberately separate

Most numbers in this project come from one of two protocols. They answer
different questions and are not comparable to each other.

| Protocol | Candidates scored | Answers |
|---|---|---|
| **Candidate-list** | MIND's supplied candidate list for each impression | How well does the model order a list someone else already chose? |
| **End-to-end serving path** | The full catalog, retrieved live | How well does the deployed pipeline do the whole job? |

Candidate-list numbers are much higher, because ordering a short
pre-filtered list is a far easier task than finding items in a catalog of
51,282. Reading one as the other overstates the system substantially.

- [`evaluation-protocol.md`](experiments/evaluation-protocol.md) — frozen metrics, splits and definitions
- [`serving-path-end-to-end-evaluation.md`](experiments/serving-path-end-to-end-evaluation.md) — the full-catalog measurement
- [`splits.md`](experiments/splits.md) — train, validation and replay

## Split status

Three states, and none of them is an untouched final split:

- **train** — model fitting, plus an internal fit/tuning partition
- **validation** — post-selection development evaluation; used for
  selection, so not a generalization estimate
- **replay** — streaming and replay analysis; no longer untouched

## Results

| Stage | Document | Report |
|---|---|---|
| Baselines | [`baselines.md`](experiments/baselines.md) | [`baseline-evaluation.json`](../reports/baseline-evaluation.json) |
| Retrieval | [`retrieval-evaluation.md`](experiments/retrieval-evaluation.md) | [`retrieval-evaluation.json`](../reports/retrieval-evaluation.json) |
| Ranking | [`ranking-evaluation.md`](experiments/ranking-evaluation.md) | [`ranking-evaluation.json`](../reports/ranking-evaluation.json) |
| Reranking | [`reranking-evaluation.md`](experiments/reranking-evaluation.md) | [`reranking-evaluation.json`](../reports/reranking-evaluation.json) |
| All stages | [`stage-comparison.md`](experiments/stage-comparison.md) | [`stage-comparison.json`](../reports/stage-comparison.json) |
| Ablations | [`ablations.md`](experiments/ablations.md) | [`ablation.json`](../reports/ablation.json) |
| Failure modes | [`failure-analysis.md`](experiments/failure-analysis.md) | [`failure-analysis.json`](../reports/failure-analysis.json) |
| End to end | [`serving-path-end-to-end-evaluation.md`](experiments/serving-path-end-to-end-evaluation.md) | [`end-to-end-evaluation.json`](../reports/end-to-end-evaluation.json) |
| Explanations | [`explanation-evaluation.md`](experiments/explanation-evaluation.md) | [`explanation-evaluation.json`](../reports/explanation-evaluation.json) |
| Serving latency | [`serving-latency.md`](experiments/serving-latency.md) | [`serving-latency.json`](../reports/serving-latency.json) |

**Evidence status.** Every evaluation table on this page is backed by a
committed, provenance-valid machine-readable report. No report was
backfilled with inferred or false provenance.

## Integrity

- [`evaluation-integrity.md`](experiments/evaluation-integrity.md) — leakage found in tuning decisions, and the fold that fixed it
- [`min-fresh-experiment-protocol.md`](experiments/min-fresh-experiment-protocol.md) — a protocol frozen before the run that tested it
- [`experiment-tracking.md`](experiments/experiment-tracking.md) — the run log
- [`../reports/`](../reports/) — machine-readable results with definitions, denominators, sampling and provenance
- [`../provenance/build-receipt.json`](../provenance/build-receipt.json) — the commit, script hash, artifact hashes and seeds the reports were computed from

## Limitations

Every relevance number here measures agreement with MIND's own already
deployed system. No live A/B test was run, by frozen scope. Read
[`limitations.md`](limitations.md) before quoting any figure, and
[`conclusions.md`](conclusions.md) for what the evidence does and does not
support.
