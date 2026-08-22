# Ablations

A component-level ablation asks how much removing just one piece of the
system costs, holding everything else fixed. This project has five real
components worth isolating: retrieval features, the ranker's own
handcrafted features, reranking, recent streaming features, and the
approximate index. Three of the five were already measured as a side
effect of earlier phases comparing pipeline stages against each other;
this document names all five in one place and adds real code for the two
that were never actually isolated on their own.
Implementation: `src/recommender/evaluation/ablations.py`.

## The matrix

| Component removed | Status | Source |
|---|---|---|
| Retrieval features | New | Ranker retrained without `retrieval_score` as an input |
| Ranker features | Reused | Already tracked as sorting by raw `retrieval_score` alone |
| Reranking | Reused | Already tracked as the ranked-only row of the Phase 5 tradeoff table |
| Recent streaming features | New | Replay evaluation with a durable-only toggle, run next step |
| Cache/index settings | Reused | Already tracked as the exact-vs-approximate index sweep |

## Why three ablations are reused, not recomputed

Sorting by raw retrieval score alone, serving the ranking model's own
slate with no reranking pass, and searching an approximate index instead
of an exact one are exactly what earlier phases already measured while
comparing pipeline stages to each other (`docs/ranking-evaluation.md`,
`docs/reranking-evaluation.md`, `docs/candidate-index.md`). Recomputing
them here would produce the same real numbers under a new name, with a
real chance of quietly drifting from the tracked originals if anything in
the surrounding code changed since they were first measured.

## The retrieval-features ablation

`run_no_retrieval_score_ablation()` retrains the ranking model with
`retrieval_score` dropped from its own input features, keeping
`category_match`, `content_similarity`, `user_history_length`, and
`hour_of_day` unchanged. It calls the exact same training and scoring
path the real production ranking model uses
(`recommender.ranking.train.train_ranking_model`,
`recommender.evaluation.evaluate_ranking._evaluate_by_score`) with a
different feature-column list, rather than a second, separately written
routine that could drift from the real one.

**Real result** (same 30,270 validation impressions, K=10), logged as
`ablation_no_retrieval_score_k10`:

| Metric | Full ranking model | Retrieval feature removed | Change |
|---|---|---|---|
| Hit rate@10 | 0.6801 | 0.6589 | −3.1% |
| Recall@10 | 0.5975 | 0.5775 | −3.3% |
| NDCG@10 | 0.3670 | 0.3545 | −3.4% |
| MRR | 0.3347 | 0.3252 | −2.8% |
| Catalog coverage@10 | 0.0712 | 0.0732 | +2.8% |

This was a predicted result, checked rather than assumed: the ranking
model's own fitted coefficients (`docs/ranking-features.md`, Step 4.3)
already showed `retrieval_score` carrying the largest weight of any
feature by a wide margin, so removing it should cost real ground on
every relevance metric. It does, consistently. Coverage moving slightly
upward is consistent with the same pattern already seen when a stronger,
more concentrated ranking signal is removed (the ranker relies more on
category/content-similarity ties, spreading recommendations across
marginally more distinct items).

## The recent-streaming-features ablation

Not yet run. The design is: `recommender.tracking.replay_evaluation`'s
existing replay harness (Step 9.2) gains one toggle that forces
`RecentUserFeatures` to look empty for every user, so the online
pipeline serves durable features only, as if no live Kafka/Redis feed
existed at all. Measured alongside every other ablation's numbers in the
next step's consolidated tradeoff table.
