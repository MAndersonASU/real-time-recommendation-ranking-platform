# Experiment Tracking

Every evaluation result across this project, so far, has lived in its
own report JSON with its own shape — real numbers, but scattered, with
no way to compare two runs without opening both files by hand.
Implementation: `src/recommender/tracking/experiment_log.py`,
backfilled by `src/recommender/tracking/backfill.py`.

## MLflow was evaluated, and rejected, with real evidence

This project's own complexity-boundary policy is to introduce a tracking
tool only if it actually reduces manual tracking. A dry-run install
(`pip install mlflow --dry-run`) against this project's real
environment showed the real cost: it would downgrade the pinned
`pandas` from 3.0.5 to 2.3.3, and pull in roughly 60 additional
packages — Flask, aiohttp, matplotlib, OpenTelemetry, a full web
server stack — for a solo project with about a dozen real experiments
total and no team collaboration surface to justify a tracking UI.
That's a real, measured cost, not a guess, and it doesn't clear this
project's own complexity-boundary policy: no tool without a measured
requirement. (Two `.gitignore` entries anticipating MLflow, `mlruns/`
and `mlflow.db`, left over from the project's original stack outline
in Phase 0, were removed as part of this decision — dead configuration
for a tool this project isn't using.)

## What was built instead

A single append-only JSONL log. `log_run(run_name, params, metrics,
notes)` appends one record — including the exact git commit the project
was at when the run was recorded, real reproducibility identity at
essentially no dependency cost. `load_runs()` reads every record back
into one flat, queryable table, one row per run, every metric and
parameter as its own column. That table is the actual payoff a tracking
tool is supposed to provide: comparing runs side by side became one
function call instead of opening N separate files.

## Backfilled with real historical results, not fabricated ones

`backfill.py` reads the real, already-computed report files from every
earlier phase — Phase 2's three baselines, Phase 3's retrieval
evaluation, Phase 4's ranking comparison, Phase 5's reranking result —
and logs each as a structured run. Two pairs of runs share a
near-identical name in the source data but measure genuinely different
things, and are kept explicitly distinct here rather than collapsed:

- `retrieval_full_catalog_n100` (`docs/retrieval-evaluation.md`) — the
  two-tower model alone, searching the whole ~51,000-item catalog.
  Weak: 0.44% hit rate.
- `retrieval_score_as_sort_key_k10` (`docs/ranking-evaluation.md`) —
  the same model's raw
  score, used only to sort MIND's own small, already-narrowed candidate
  pool. A much easier task, and a much higher number (66.0% hit rate)
  — the exact asymmetry documented in `docs/inference-path.md`.

As a real cross-check, `ranking_model_k10` and
`reranking_ranked_only_k10` — logged from two entirely separate report
files, produced by two separate evaluation scripts run at different
times — came back with identical metrics (68.0% hit rate, 0.367 NDCG),
since the second is defined as the ranking model's own output before
reranking is applied. Two independently-produced files agreeing exactly
is a small, genuine confirmation that both pipelines are measuring the
same thing correctly.
