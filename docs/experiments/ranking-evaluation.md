# Candidate-list ranking evaluation

Source: [`reports/ranking-evaluation.json`](../../reports/ranking-evaluation.json).

This comparison asks whether the trained ranker orders a fixed candidate
list better than the two-tower score alone.

Both arms use:

- all 30,270 validation impressions;
- the same MIND candidate rows;
- K = 10; and
- the same frozen metric definitions.

Only the sort value changes:

| Arm | Sort value |
|---|---|
| Retrieval score only | Two-tower dot product |
| Ranked | Predicted click probability from the five-input ranker |

Implementation:
`src/recommender/evaluation/evaluate_ranking.py`.

## Result

| Metric | Retrieval score only | Ranked |
|---|---|---|
| Hit rate@10 | 0.6689 | 0.6828 |
| Recall@10 | 0.5864 | 0.5999 |
| NDCG@10 | 0.3518 | 0.3671 |
| MRR | 0.3169 | 0.3340 |
| Catalog coverage@10 | 0.0654 | 0.0678 |

The ranker improves every reported measure on the same candidates. The
difference comes from category match, content similarity, history
length, and hour of day in addition to the retrieval score.

## Comparison with baselines

| Metric | Popularity | Content similarity | Collaborative | Retrieval score only | Ranked |
|---|---|---|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 | 0.5709 | 0.6689 | **0.6828** |
| Recall@10 | 0.5034 | 0.5743 | 0.5046 | 0.5864 | **0.5999** |
| NDCG@10 | 0.2830 | 0.3526 | 0.2847 | 0.3518 | **0.3671** |
| MRR | 0.2484 | 0.3236 | 0.2509 | 0.3169 | **0.3340** |
| Catalog coverage@10 | 0.0370 | 0.0722 | 0.0389 | 0.0654 | 0.0678 |

The ranker has the best relevance values in this candidate-list
comparison. Content similarity has slightly higher catalog coverage.

## Why this does not equal full-catalog retrieval

Hit rate@10 of 0.6689 for retrieval-score ordering is not comparable to
hit rate@100 of 0.0336 in the
[full-catalog retrieval evaluation](retrieval-evaluation.md).

Here, the clicked item is usually already included in a small
MIND-supplied candidate list. Full-catalog retrieval must first find the
item among 51,282 articles. These protocols measure different tasks.

The older category-vector collapse made full-catalog retrieval worse,
but the candidate-pool difference remains even after that defect was
corrected.

## Answer to RQ2

Given the same candidate list, the dedicated ranker improves ordering
over the two-tower score alone across all five reported measures.

This conclusion applies to the candidate-list protocol. For what a live
request receives after retrieval and reranking, use the
[serving-path evaluation](serving-path-end-to-end-evaluation.md).

Supporting checks:

- [ranking dataset](ranking-dataset.md);
- [ranking features](ranking-features.md);
- [ranking model](ranking-model.md); and
- [calibration](ranking-calibration.md).
