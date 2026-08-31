# Component ablations

Source: [`reports/ablation.json`](../../reports/ablation.json).

An ablation removes one component while keeping the surrounding
evaluation fixed. This page gathers five such comparisons. Two were run
specifically for this report; three reuse an earlier comparison that
already removed the same component.

Implementation:
`src/recommender/evaluation/ablations.py`.

## Evidence map

| Component removed | Status | Source |
|---|---|---|
| Retrieval features | New | Ranker retrained without `retrieval_score` as an input |
| Ranker features | Reused | Already tracked as sorting by raw `retrieval_score` alone |
| Reranking | Reused | Already tracked as the ranked-only row of the reranking tradeoff table |
| Recent streaming features | New | Replay evaluation with a durable-only toggle |
| Cache/index settings | Reused | Already tracked as the exact-vs-approximate index sweep |

Reusing an exact earlier comparison avoids recomputing the same
measurement under a new name and then letting the two copies drift.

## Remove the retrieval score from ranking

`run_no_retrieval_score_ablation()` retrains the ranker without
`retrieval_score`. Category match, content similarity, history length,
and hour remain unchanged. Training and scoring use the normal ranking
implementation with a different input list.

The run uses all 30,270 validation impressions and K=10.

| Metric | Full ranking model | Retrieval feature removed | Change |
|---|---|---|---|
| Hit rate@10 | 0.6828 | 0.6589 | −3.5% |
| Recall@10 | 0.5999 | 0.5775 | −3.7% |
| NDCG@10 | 0.3671 | 0.3545 | −3.4% |
| MRR | 0.3340 | 0.3252 | −2.6% |
| Catalog coverage@10 | 0.0678 | 0.0732 | +8.0% |

Removing the ranker's strongest fitted input lowers every relevance
measure. Coverage rises because the weaker ordering spreads selections
over slightly more articles.

## Disable recent Redis features

`evaluate_via_replay` accepts `use_recent_features=False`. That setting
skips Redis and uses durable history when available, then global
popularity. Both arms use the same seeded 500-impression replay sample.

The real ambient Redis store was flushed before this run:

| | With recent features | Without recent features |
|---|---|---|
| Hit rate@10 | 0.0 | 0.0 |
| Mean feature-lookup latency | 1.78ms | 0.012ms |

The equal quality value does not show that recent features are useless.
Redis contained no recent record for any sampled user, so both arms used
the same durable-history or popularity fallback. A deployment with
accumulated Redis history could differ.

The latency comparison is still real. Enabling recent features performs
a Redis round trip even when no record exists; disabling them skips it.
The exact ratio depends on current machine and network load.

## Consolidated tradeoffs

| Component removed | Quality cost | Latency saved |
|---|---|---|
| Retrieval features | Hit rate −3.5%, NDCG −3.4% | None measured (same code path) |
| Ranker features | Hit rate ≈−2.0%, NDCG ≈−4.1% | ~1.73ms p50 (ranking stage) |
| Reranking | Relevance rises (hit rate ≈+2.3%, NDCG ≈+1.7%), but mean distinct categories 5.42→4.70 and slates below the freshness quota 74.0%→82.0% | ~9.89ms p50 (~31% of total request time) |
| Recent streaming features | Unchanged in this run (0.0→0.0 hit rate; real ambient Redis was empty in both arms at measurement time, see above) | 1.78ms→0.012ms mean feature lookup |
| Cache/index settings | Recall vs. exact drops to 0.624 at nprobe=8 (0.891 at nprobe=32) | ~12.6x faster than exact search at nprobe=8 (5.0μs vs. 63.1μs) |

## Do not combine the protocols

These rows summarize different controlled comparisons:

- retrieval and ranker feature rows use the K=10 validation
  candidate-list protocol;
- the reranking row uses the same candidate list but measures slate
  policy;
- recent features use a replay sample and real ambient Redis; and
- index settings compare approximate with exact Faiss search.

The table is a navigation aid, not one common experiment. Use the source
pages for denominators and interpretation:

- [ranking evaluation](ranking-evaluation.md);
- [reranking evaluation](reranking-evaluation.md);
- [replay evaluation](replay-evaluation.md); and
- [archived Faiss measurement](../archive/faiss-index.md).
