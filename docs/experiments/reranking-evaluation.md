# Reranking tradeoffs

Source: [`reports/reranking-evaluation.json`](../../reports/reranking-evaluation.json).

This evaluation compares the plain ranked top 10 with the top 10 after:

1. diversity constraints; and
2. the freshness quota.

Both arms use all 30,270 validation impressions, the same candidates,
the same ranking scores, and K=10.

Implementation:
`src/recommender/evaluation/evaluate_reranking.py`.

## Metric scope

MRR is the first clicked item within the returned 10-item slate. There
is no longer ordering beyond that slate after reranking.

Recall and NDCG still use the number of clicks in the full candidate
list as their denominator. This prevents a 10-item slice from hiding
relevant items that were not selected.

## Result

| Metric | Ranked only | Reranked | Change |
|---|---|---|---|
| Hit rate@10 | 0.6828 | 0.6675 | −2.2% |
| Recall@10 | 0.5999 | 0.5848 | −2.5% |
| NDCG@10 | 0.3671 | 0.3610 | −1.7% |
| MRR (slate-scoped) | 0.3182 | 0.3158 | −0.8% |
| Mean distinct categories | 4.70 | 5.42 | +15.1% |
| Mean max-category count | 4.04 | 2.82 | −30.2% |
| Mean fresh fraction | 0.0833 | 0.0946 | +13.5% relative |
| Slates below the fresh quota | 82.0% | 74.0% | −9.8% relative |
| Catalog coverage@10 | 0.0678 | 0.0652 | −3.8% |

## Interpretation

| Area | Outcome |
|---|---|
| Relevance | Every measure declines, with the largest drop at 2.5% |
| Category diversity | Distinct categories rise and category concentration falls |
| Freshness proxy | Fresh share rises modestly; quota misses remain common |
| Catalog coverage | Falls by 3.8% |

Category diversity improved substantially. The dominant category shrank
from 4.04 to 2.82 items, while mean distinct categories rose from 4.70
to 5.42.

Fresh share rose from 8.33% to 9.46%. Slates below the quota fell from
82% to 74%, so the policy helps but often lacks enough known-age,
eligible supply.

Catalog coverage measures variety across all users. The policy can only
reorder candidates already present in one impression, so more variety
within a slate does not guarantee more catalog-wide variety.

## Corrected recall and NDCG calculation

The first run passed only the returned 10 items to generic Recall and
NDCG functions. The functions then treated the slate as the complete
candidate set, making Recall equal Hit rate.

The evaluation now uses `recall_at_n_known_total` and
`ndcg_at_n_known_total` with the true click count from the full
candidate group. A regression test includes a relevant item outside the
slate and confirms the correct Recall is 0.5 rather than 1.0.

## Answer to RQ3

For this candidate-list protocol, reranking produces better category
diversity and a modest improvement in the freshness proxy at a relevance
loss of no more than 2.5% on the reported measures. Catalog-wide
coverage decreases.

Whether that tradeoff is acceptable is a product choice, not a fact the
offline evaluation can decide.

See [diversity reranking](reranking-diversity.md) and
[freshness reranking](reranking-freshness.md).
