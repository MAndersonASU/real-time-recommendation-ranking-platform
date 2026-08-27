# Comparing Model Stages

Orders every stage of the pipeline — the strongest baseline, retrieval,
ranking, reranking — into one table, using the experiment log built in
`docs/experiments/experiment-tracking.md`, and computes each metric's change from
the stage immediately before it. Implementation:
`src/recommender/tracking/stage_comparison.py`.

## The same governed contract throughout

Every stage compared here was evaluated on the identical protocol: K=10,
the same 30,270 validation impressions, frozen since the baselines
(`docs/experiments/evaluation-protocol.md`). A delta between adjacent rows reflects
exactly the one stage that changed, not a different evaluation
population or a different K creeping in unnoticed.

## The comparison against the best baseline, not the weakest

Content similarity — not popularity, not collaborative filtering — is
the anchor, since it beat both of the other baselines on every metric.
Comparing the pipeline's cumulative gain against the weakest baseline
would overstate how much retrieval, ranking, and reranking actually add
on top of the best pre-existing approach.

## Results

| Stage | Hit rate@10 | Recall@10 | NDCG@10 | Δ hit rate | Δ NDCG |
|---|---|---|---|---|---|
| Best baseline (content similarity) | 0.6557 | 0.5743 | 0.3526 | — | — |
| Retrieval | 0.6689 | 0.5864 | 0.3518 | +0.0132 | **−0.0008** |
| Ranking | 0.6828 | 0.5999 | 0.3671 | +0.0139 | +0.0153 |
| Reranking | 0.6675 | 0.5848 | 0.3610 | −0.0153 | −0.0061 |

## A nuance only visible once the numbers sit side by side

Retrieval alone slightly *beats* content similarity on hit rate and
recall, but slightly *loses* to it on NDCG — a small, regression
that was true in the underlying report files all along, but invisible
until this check put both rows next to each other. It means retrieval
finds a true click inside its top-10 slightly more often, but on
average ranks that click a little lower within the slate than content
similarity's own ordering does. The ranking model then more than
recovers that ground on every metric, and reranking spends part of
ranking's own gain on diversity and freshness — the same tradeoff
reranking already measured, now visible in the same table as everything
that came before and after it.
