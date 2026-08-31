# Evaluation

This page is the index for measured results. Each result has:

- a readable explanation under `docs/experiments/`; and
- a machine-readable JSON report under `reports/`.

Read [limitations](limitations.md) before using any number outside this
project.

## Start with the right protocol

The project uses two evaluation protocols. They answer different
questions.

| Protocol | What it scores | What it tells us |
|---|---|---|
| Candidate list | MIND's short list for an impression | How well does the model order items that were already selected? |
| End-to-end serving | Items retrieved from the full 51,282-item catalog | How well does the assembled recommendation path work? |

Candidate-list results are much higher because the clicked item is
already in the list. End-to-end serving must find that item before
ranking can help. Do not use a candidate-list result as a claim about
the complete system.

For definitions and sampling rules, see
[evaluation protocol](experiments/evaluation-protocol.md). For the
complete-system measurement, see
[end-to-end evaluation](experiments/serving-path-end-to-end-evaluation.md).

## Data splits

| Split | Use |
|---|---|
| Train | Model fitting, including the internal fit and tuning partition |
| Validation | Development evaluation after model selection |
| Replay | Streaming and replay analysis |

None of these is an untouched final test set. The validation and replay
data have both informed development decisions. See
[time-aware splits](experiments/splits.md).

## Published results

| Topic | Readable document | JSON report |
|---|---|---|
| Baselines | [Baselines](experiments/baselines.md) | [`baseline-evaluation.json`](../reports/baseline-evaluation.json) |
| Retrieval | [Retrieval evaluation](experiments/retrieval-evaluation.md) | [`retrieval-evaluation.json`](../reports/retrieval-evaluation.json) |
| Ranking | [Ranking evaluation](experiments/ranking-evaluation.md) | [`ranking-evaluation.json`](../reports/ranking-evaluation.json) |
| Reranking | [Reranking tradeoffs](experiments/reranking-evaluation.md) | [`reranking-evaluation.json`](../reports/reranking-evaluation.json) |
| Model outputs | [Model comparison](experiments/stage-comparison.md) | [`stage-comparison.json`](../reports/stage-comparison.json) |
| Ablations | [Ablations](experiments/ablations.md) | [`ablation.json`](../reports/ablation.json) |
| Failure modes | [Failure analysis](experiments/failure-analysis.md) | [`failure-analysis.json`](../reports/failure-analysis.json) |
| Full serving path | [End-to-end evaluation](experiments/serving-path-end-to-end-evaluation.md) | [`end-to-end-evaluation.json`](../reports/end-to-end-evaluation.json) |
| Explanations | [Explanation evaluation](experiments/explanation-evaluation.md) | [`explanation-evaluation.json`](../reports/explanation-evaluation.json) |
| Serving latency | [Serving latency](experiments/serving-latency.md) | [`serving-latency.json`](../reports/serving-latency.json) |
| Tuning decisions | [Evaluation integrity](experiments/evaluation-integrity.md) | [`tuning-decisions.json`](../reports/tuning-decisions.json) |
| Fresh-item policy | [Minimum-fresh experiment](experiments/min-fresh-experiment-protocol.md) | [`min-fresh-experiment.json`](../reports/min-fresh-experiment.json) |
| Durable-history fallback | [Durable-history evaluation](experiments/durable-history-fallback.md) | [`durable-history-fallback.json`](../reports/durable-history-fallback.json) |

These 13 report families are committed and validate against the report
schema. Each report includes metric definitions, denominators, sampling
details, limitations, artifact identities, and source provenance.

## How integrity is checked

- [Evaluation integrity](experiments/evaluation-integrity.md) explains
  how tuning leakage was found and removed.
- [Minimum-fresh experiment](experiments/min-fresh-experiment-protocol.md)
  records a decision rule written before its result was known.
- [Experiment tracking](experiments/experiment-tracking.md) describes
  the JSONL run log.
- [Build receipt](../provenance/build-receipt.json) records the source
  commit, script hash, artifact hashes, and seeds used for publication.

## What the numbers cannot show

The relevance labels come from clicks collected by MIND's original
news system. They reflect that system's exposure and position bias. No
live A/B test was run, so these results do not establish user,
retention, or business impact.

Use [conclusions](conclusions.md) for supported claims and
[limitations](limitations.md) for unresolved uncertainty.
