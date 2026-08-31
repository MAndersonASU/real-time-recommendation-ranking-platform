# Comparing model outputs

Generated from [`reports/stage-comparison.json`](../../reports/stage-comparison.json).

This table compares four ways to order the same MIND candidate lists.
It uses the [experiment log](experiment-tracking.md) and calculates each
row's change from the row above it.

Implementation: `src/recommender/tracking/stage_comparison.py`.

## Important scope

Every row uses K=10 and the same 30,270 validation impressions under the
[frozen protocol](evaluation-protocol.md).

“Retrieval” in this table means ordering the supplied candidates by the
two-tower `retrieval_score`. It does not mean searching the full catalog.
Use the [retrieval evaluation](retrieval-evaluation.md) for that separate
task.

Content similarity is the baseline because it beat popularity and
collaborative filtering on every reported measure. Starting with the
weakest baseline would exaggerate later gains.

## Results

| Stage | Hit rate@10 | Recall@10 | NDCG@10 | Δ hit rate | Δ NDCG |
|---|---|---|---|---|---|
| Best baseline (content similarity) | 0.6557 | 0.5743 | 0.3526 | — | — |
| Retrieval | 0.6689 | 0.5864 | 0.3518 | +0.0132 | **−0.0008** |
| Ranking | 0.6828 | 0.5999 | 0.3671 | +0.0139 | +0.0153 |
| Reranking | 0.6675 | 0.5848 | 0.3610 | −0.0153 | −0.0061 |

## Interpretation

- Retrieval-score ordering improves Hit rate and Recall over content
  similarity but lowers NDCG by 0.0008.
- The ranker improves all three relevance measures.
- Reranking gives back part of the ranking gain to improve diversity
  and the freshness proxy.

The NDCG difference means retrieval-score ordering finds a click
slightly more often but places it slightly lower on average than content
similarity.
