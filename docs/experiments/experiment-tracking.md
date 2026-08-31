# Experiment tracking

Machine-readable reports keep complete evidence for one evaluation.
The experiment log puts selected parameters and metrics from many runs
into one comparable table.

Implementation:

- `src/recommender/tracking/experiment_log.py`
- `src/recommender/tracking/backfill.py`

## Why the project does not use MLflow

A dry-run MLflow installation would:

- downgrade pandas from 3.0.5 to 2.3.3; and
- add about 60 packages, including a web server and telemetry stack.

The project has one maintainer, a small experiment set, and no need for
a shared tracking service. That dependency cost is not justified.
Unused `mlruns/` and `mlflow.db` ignore rules were removed.

## JSONL log

`log_run(run_name, params, metrics, notes)` appends one JSON record with:

- run name;
- parameters;
- metrics;
- notes; and
- Git commit.

`load_runs()` returns a flat table with one row per run and one column
per parameter or metric.

The JSONL file is an index for comparison. The validated files under
`reports/` remain the authoritative publication records.

## Backfilled runs

`backfill.py` reads existing report JSON rather than copying values by
hand.

Two similarly named entries remain separate because they measure
different tasks:

| Run | Candidate pool | Hit rate |
|---|---|---:|
| `retrieval_full_catalog_n100` | Full 51,282-item catalog, N=100 | 3.36% |
| `retrieval_score_as_sort_key_k10` | MIND's supplied candidates, K=10 | 66.89% |

The large difference is expected. In the second run, the clicked item is
usually already present in a small candidate list.

## Cross-check

`ranking_model_k10` and `reranking_ranked_only_k10` come from separate
reports and evaluation commands. Both record about 68.3% hit rate and
0.3671 NDCG because the latter is defined as the ranker's slate before
reranking.

That agreement checks that both publication paths refer to the same
candidate-list output.

See [evaluation index](../evaluation.md) and
[full-catalog retrieval](retrieval-evaluation.md).
