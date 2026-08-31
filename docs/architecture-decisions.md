# Architecture decisions

This log records major structural choices and their reasons. Each entry
describes the project on that date. For the design that exists now, use
the [architecture guide](architecture.md).

## August 15, 2026

### Start from an empty repository

The earlier local checkout and GitHub repository no longer existed, so
no code or configuration carried forward.

### Require Python 3.11

The machine default was Python 3.14. The project uses 3.11 because
PyTorch, Faiss, and TorchRec often support new CPython versions later.

### Add dependencies only when needed

Packages are declared when a real component needs them. This reduces
unused or stale dependencies.

### Anchor the dataset ignore rule

The original `data/` pattern also matched the source package at
`src/recommender/data/`. Reading `git status` before the first commit
revealed the problem. The rule is now `/data/`, which applies only at
the repository root.

### Run CI on Ubuntu

CI uses `ubuntu-latest` even though development began on Windows. The
code is pure Python and has no intended operating-system-specific
behavior. Revisit this choice if a future dependency adds platform
requirements.

### Separate retrieval depth from served list size

The [research scenario](research-scenario.md) was fixed before
implementation. It distinguishes N, the retrieval candidate count,
from K, the number of served items. RQ1 and RQ2 measure different parts
of the system, so their results must remain separate.

## August 16, 2026

### Give evaluation its own package

`recommender.evaluation` owns Recall@K, NDCG@K, MRR, hit rate, and
coverage definitions. Both offline evaluation and replay use them.
Keeping the definitions in one package avoids assigning shared metrics
to either the ranking or streaming implementation.

### Keep baselines with ranking

`recommender/ranking/baselines.py` contains the popularity baselines.
Both a baseline and a learned ranker order a fixed candidate set, so a
new top-level package would add structure without a distinct
responsibility.

## August 21, 2026

### Use a small experiment log

`recommender.tracking` writes a JSONL log. A dry run showed that MLflow
would downgrade the pinned pandas version and add about 60 transitive
packages for a small number of experiments. The lighter local format
fits the project better. See [experiment tracking](experiments/experiment-tracking.md).

## August 22, 2026

### Isolate optional explanations

`recommender.explanation` receives only a completed
`RecommendationResponse`. It is separate from `recommender.serving` so
optional explanation code cannot access or change in-progress ranking
state. See the
[explanation boundary](experiments/explanation-boundary.md).
