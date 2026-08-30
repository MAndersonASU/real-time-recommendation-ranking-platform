# Ablations

Generated from [`reports/ablation.json`](../../reports/ablation.json).

A component-level ablation asks how much removing just one piece of the
system costs, holding everything else fixed. This project has five real
components worth isolating: retrieval features, the ranker's own
handcrafted features, reranking, recent streaming features, and the
approximate index. Three of the five were already measured as a side
effect of earlier work comparing pipeline stages against each other;
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
of an exact one are exactly what earlier evaluations already measured while
comparing pipeline stages to each other (`docs/experiments/ranking-evaluation.md`,
`docs/experiments/reranking-evaluation.md`, `docs/archive/faiss-index.md`). Recomputing
them here would produce the same numbers under a new name, with a
real chance of quietly drifting from the tracked originals if anything in
the surrounding code changed since they were first measured.

## The retrieval-features ablation

`run_no_retrieval_score_ablation()` retrains the ranking model with
`retrieval_score` dropped from its own input features, keeping
`category_match`, `content_similarity`, `user_history_length`, and
`hour_of_day` unchanged. It calls the exact same training and scoring
path the serving-path ranking model uses
(`recommender.ranking.train.train_ranking_model`,
`recommender.evaluation.evaluate_ranking._evaluate_by_score`) with a
different feature-column list, rather than a second, separately written
routine that could drift from the real one.

**Results** (same 30,270 validation impressions, K=10), logged as
`ablation_no_retrieval_score_k10`:

| Metric | Full ranking model | Retrieval feature removed | Change |
|---|---|---|---|
| Hit rate@10 | 0.6828 | 0.6589 | −3.5% |
| Recall@10 | 0.5999 | 0.5775 | −3.7% |
| NDCG@10 | 0.3671 | 0.3545 | −3.4% |
| MRR | 0.3340 | 0.3252 | −2.6% |
| Catalog coverage@10 | 0.0678 | 0.0732 | +8.0% |

This was a predicted result, checked rather than assumed: the ranking
model's own fitted coefficients (`docs/experiments/ranking-features.md`)
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

**Results**, same seeded 500-impression real replay sample used in both
arms (`recommender.tracking.recent_features_ablation`, which asserts
both arms drew the identical sample before reporting anything), logged
as `ablation_recent_features_replay_paired`. Re-measured after
SERVING-DURABLE-HISTORY-69's fix, with the real ambient Redis store
flushed clean immediately beforehand (disclosed below, not hidden --
this run's own real Redis content, not a controlled isolated one, is
what `evaluate_via_replay` measures against, its own long-disclosed
limitation):

| | With recent features | Without recent features |
|---|---|---|
| Hit rate@10 | 0.0 | 0.0 |
| Mean feature-lookup latency | 1.78ms | 0.012ms |

**Zero quality cost in this run, for a reason that changed with the
fix.** Before SERVING-DURABLE-HISTORY-69, both arms fell all the way to
the global-popularity candidate pool for a user with no live Redis
record, regardless of whether they had durable history -- the toggle
genuinely had no headroom to change anything, since retrieval never
looked past `recent_clicked_items` at all.

After the fix, retrieval falls back to a user's durable history when
Redis has nothing usable, before falling to popularity
(`recommender.serving.pipeline.select_retrieval_history`). That
changes what "zero difference" means here: with the real ambient Redis
store flushed clean for this measurement, `with_recent_features=True`
finds no record for any user in this sample -- the identical starting
point `use_recent_features=False` forces outright -- so both arms
necessarily fall back to the same source (durable history where a user
has it, global popularity where they don't) for every impression in
this specific run. That is a fact about this run's Redis contents at
measurement time, not a structural property of the retrieval path
anymore: a live deployment with real accumulated Redis state would show
`with_recent_features=True` diverge from `without` specifically for a
user who has a real recent record, which this evaluation's methodology
(matching whatever Redis holds *right now*, not a controlled isolated
store) cannot demonstrate without one. The latency side remains real
and unambiguous regardless: `with_recent_features=True` still pays a
real network round trip to Redis even when it finds nothing, and
`False` skips the attempt entirely -- ~150x here, consistent in order
of magnitude with the isolated Redis round-trip latency measured when
the low-latency store was first built (`docs/operations/state-store.md`,
0.29ms p50/1.12ms p99). The exact ratio moves between runs with real
ambient system load, not just with what's in Redis.

## Consolidated quality-latency tradeoff table

| Component removed | Quality cost | Latency saved |
|---|---|---|
| Retrieval features | Hit rate −3.5%, NDCG −3.4% | None measured (same code path) |
| Ranker features | Hit rate ≈−2.0%, NDCG ≈−4.1% | ~1.73ms p50 (ranking stage) |
| Reranking | Relevance rises (hit rate ≈+2.3%, NDCG ≈+1.7%), but mean distinct categories 5.42→4.70 and slates below the freshness quota 74.0%→82.0% | ~9.89ms p50 (~31% of total request time) |
| Recent streaming features | Unchanged in this run (0.0→0.0 hit rate; real ambient Redis was empty in both arms at measurement time, see above) | 1.78ms→0.012ms mean feature lookup |
| Cache/index settings | Recall vs. exact drops to 0.624 at nprobe=8 (0.891 at nprobe=32) | ~12.6x faster than exact search at nprobe=8 (5.0μs vs. 63.1μs) |

Every relevance number above comes from the same frozen K=10/validation
protocol (`docs/experiments/evaluation-protocol.md`); every latency number comes
from a measurement already on record or captured directly in this
analysis, never estimated.
