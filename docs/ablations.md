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
| Reranking | Reused | Already tracked as the ranked-only row of the reranking tradeoff table |
| Recent streaming features | New | Replay evaluation with a durable-only toggle |
| Cache/index settings | Reused | Already tracked as the exact-vs-approximate index sweep |

## Why three ablations are reused, not recomputed

Sorting by raw retrieval score alone, serving the ranking model's own
slate with no reranking pass, and searching an approximate index instead
of an exact one are exactly what earlier phases already measured while
comparing pipeline stages to each other (`docs/ranking-evaluation.md`,
`docs/reranking-evaluation.md`, `docs/faiss-index.md`). Recomputing
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
model's own fitted coefficients (`docs/ranking-features.md`)
already showed `retrieval_score` carrying the largest weight of any
feature by a wide margin, so removing it should cost real ground on
every relevance metric. It does, consistently. Coverage moving slightly
upward is consistent with the same pattern already seen when a stronger,
more concentrated ranking signal is removed (the ranker relies more on
category/content-similarity ties, spreading recommendations across
marginally more distinct items).

## The recent-streaming-features ablation

`recommender.tracking.replay_evaluation.evaluate_via_replay` gained a
`use_recent_features` toggle, threaded through `recommend()` and
`safe_recommend()` down to `get_online_features()`
(`recommender.features.cold_start`): when False, the online lookup
skips Redis entirely and falls back to the same neutral default a
genuinely new user already gets, rather than a second kind of "no
data." Each call's real `feature_lookup_ms` is captured via
`stage_timings` so the latency side of this ablation, not just its
quality side, is measured directly rather than estimated.

**Real result**, same 500-impression real replay sample used both with
and without the toggle, logged as `ablation_no_recent_features_replay`
and `ablation_with_recent_features_replay`:

| | With recent features | Without recent features |
|---|---|---|
| Hit rate@10 | 0.0 | 0.0 |
| Mean feature-lookup latency | 0.80ms | 0.008ms |

**Zero quality cost, for a reason already on record, not a new
finding**: this replay population was already measured at the
cold-start floor (`docs/limitations.md`, `docs/replay-evaluation.md`) —
near-total absence
of durable/recent feature overlap collapses the two-tower embedding to
a near-identical vector regardless, so there is no headroom left for
recent features to lose. The latency side is real and unambiguous: a
~100x drop in mean feature-lookup time, consistent in order of
magnitude with the isolated Redis round-trip latency measured when the
low-latency store was first built (`docs/state-store.md`, 0.29ms
p50/1.12ms p99).

## Consolidated quality-latency tradeoff table

| Component removed | Quality cost | Latency saved |
|---|---|---|
| Retrieval features | Hit rate −3.1%, NDCG −3.4% | None measured (same code path) |
| Ranker features | Hit rate −2.9%, NDCG −6.1% | ~1.49ms p50 (ranking stage) |
| Reranking | Relevance rises (hit rate +1.8%, NDCG +1.4%), but mean distinct categories 5.33→4.50 and slates below the freshness quota 4.8%→13.3% | ~8.88ms p50 (69% of total request time) |
| Recent streaming features | Unchanged (0.0→0.0 hit rate, already at the cold-start floor) | 0.80ms→0.008ms mean feature lookup |
| Cache/index settings | Recall vs. exact drops to 0.624 at nprobe=8 (0.891 at nprobe=32) | ~12.6x faster than exact search at nprobe=8 (5.0μs vs. 63.1μs) |

Every relevance number above comes from the same frozen K=10/validation
protocol (`docs/evaluation-protocol.md`); every latency number comes
from a real measurement already on record or captured directly in this
step, never estimated.
