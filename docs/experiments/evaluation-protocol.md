# Evaluation Protocol (Frozen)

Locked 2026-08-18, after the baselines' three baselines already had results measured under it. Changing any item below after that point would
invalidate every comparison already made in `docs/experiments/baselines.md` — the same
principle `docs/research-scenario.md` already applies to the research
questions themselves.

## What's frozen

- **Evaluation split**: `validation` (`docs/experiments/splits.md`) — 30,270
  impressions from 2019-11-14. Never used for gradient-based training.
  **Correction (docs/experiments/evaluation-integrity.md)**: three feature/
  hyperparameter decisions (dropping `popularity` from the ranking
  model, the diversity category cap, the freshness threshold) were, in
  fact, originally chosen by looking at measurements on this same
  split, then reported against it — real leakage, not previously
  disclosed here. Fixed going forward: any future such decision uses
  `recommender.evaluation.tuning_fold`, a held-out fold carved from
  `train`, never validation.
- **`replay` (2019-11-15)**: designated for streaming replay and replay
 evaluation, and used exactly that way —
  `recommender.tracking.replay_evaluation.evaluate_via_replay` has
  already run against it (`docs/experiments/replay-evaluation.md`). **Correction**:
  an earlier version of this document called it "untouched by any
  evaluation to date," which stopped being accurate once that
  evaluation ran and was never updated here. Still never used for
  gradient-based training, and still never used to make a feature or
  hyperparameter decision later reported against it (the leakage
  pattern the correction above describes) — but it is not an unused,
  fully reserved split.
- **K = 10** for every Top-K metric (Recall@K, NDCG@K, hit rate@K,
  catalog coverage@K). A result reported at a different K is a different,
  not-directly-comparable number.
- **Metrics**: `hit_rate_at_k`, `recall_at_k`, `ndcg_at_k`,
  `reciprocal_rank` (MRR), `catalog_coverage` — defined once in
  `src/recommender/evaluation/metrics.py`, hand-verified against a
  worked example (`tests/test_metrics.py`) before any baseline used them.
- **Catalog size for coverage**: the `train` split's `news.parquet` row
  count (51,282) — the same catalog both `train` and `validation` draw
  from.
- **Candidate set (the baselines only)**: exactly the items listed in
  MIND's own `impressions` field for that row. No candidate generation
  happens at this stage. This definition does not automatically extend to
 the retrieval model: a real retrieval system generates its own candidate sets from
  the full catalog rather than reusing MIND's pre-built impression lists,
 so the retrieval model needs its own explicit candidate-set definition rather than
  silently inheriting this one.

## Enforced, not just documented

`src/recommender/evaluation/contract.py` centralizes the split paths, the
catalog path, and `TOP_K` as the single source every evaluation script
imports from. `src/recommender/evaluation/evaluate_baseline.py` was
refactored in this check to import from it instead of redefining its own
copies of these values — verified to produce bit-for-bit identical results
to the pre-refactor numbers already published in `docs/experiments/baselines.md`.
`tests/test_contract.py` asserts the frozen values directly, so an
accidental future change can't pass CI silently.

## Results locked under this protocol

See `docs/experiments/baselines.md` for full detail. Summary (K=10, same 30,270
validation impressions throughout):

| | Popularity | Content similarity | Collaborative |
|---|---|---|---|
| Hit rate | 0.5697 | 0.6557 | 0.5709 |
| NDCG | 0.2830 | 0.3526 | 0.2847 |
| Catalog coverage | 0.0370 | 0.0722 | 0.0389 |

## What would break this contract

Changing K, swapping the validation split for a different one, altering
what counts as a candidate, or redefining a metric after these baseline
numbers exist would invalidate the comparisons above. Any of those needs
to be treated as a new, explicitly versioned protocol — with its own
re-run of all three baselines under the new conditions — not a silent
edit to this document or to `contract.py`.
