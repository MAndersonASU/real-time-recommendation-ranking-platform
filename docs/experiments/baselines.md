# Baseline comparison

Source: [`reports/baseline-evaluation.json`](../../reports/baseline-evaluation.json).

All three baselines rank the candidate list already supplied in each
MIND validation impression. They use K=10 and all 30,270 validation
impressions under the [frozen protocol](evaluation-protocol.md).

## Result at a glance

| Metric | Popularity | Content similarity | Collaborative |
|---|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 | 0.5709 |
| Recall@10 | 0.5034 | 0.5743 | 0.5046 |
| NDCG@10 | 0.2830 | 0.3526 | 0.2847 |
| MRR | 0.2484 | 0.3236 | 0.2509 |
| Catalog coverage@10 | 0.0370 | 0.0722 | 0.0389 |

Content similarity is the strongest baseline on every reported measure.
Collaborative filtering is only slightly better than popularity because
most validation articles have no training clicks.

These are candidate-list results. They do not measure retrieval from the
full catalog and should not be compared directly with end-to-end
serving results.

## Popularity

The popularity baseline orders candidates by training click count. It
uses no user or content information.

| Metric | Value |
|---|---|
| Hit rate@10 | 0.5697 |
| Recall@10 | 0.5034 |
| NDCG@10 | 0.2830 |
| MRR | 0.2484 |
| Catalog coverage@10 | 0.0370 |

It recommends 1,896 distinct articles from a 51,282-item catalog.
Strong hit rate is possible because clicks are concentrated on a small
popular set. Coverage reveals the cost: only 3.70% of the catalog ever
appears in a top 10.

The evaluation took about 41 seconds locally. It remains a simple
offline script because serving performance, not this one-time loop, is
the measured latency target.

## Content similarity

This baseline builds a TF-IDF vector from each article's title and
abstract. A user's vector is the mean of articles in their click
history. Empty or unusable history falls back to popularity.

| Metric | Popularity | Content similarity |
|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 |
| Recall@10 | 0.5034 | 0.5743 |
| NDCG@10 | 0.2830 | 0.3526 |
| MRR | 0.2484 | 0.3236 |
| Catalog coverage@10 | 0.0370 | 0.0722 |

It recommends 3,704 distinct articles, about twice the popularity
baseline. In 772 impressions (2.5%), no usable history existed and the
baseline used popularity.

This shows that even lexical personalization is useful. It does not
answer whether learned embeddings help; the retrieval model must beat
this stronger baseline to support that claim.

## Collaborative filtering

This baseline fits 20-component TruncatedSVD user and item factors from
the training click matrix. It scores a candidate with the user-item dot
product. A candidate unseen in training scores `-inf`. A user with no
training history receives the popularity fallback.

| Metric | Popularity | Content similarity | Collaborative |
|---|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 | 0.5709 |
| Recall@10 | 0.5034 | 0.5743 | 0.5046 |
| NDCG@10 | 0.2830 | 0.3526 | 0.2847 |
| MRR | 0.2484 | 0.3236 | 0.2509 |
| Catalog coverage@10 | 0.0370 | 0.0722 | 0.0389 |

Only 29.2% of validation candidate articles had a training click,
although 80.2% of validation users had a known factor. About 71% of
candidates therefore had no collaborative score. In 4,958 impressions
(16.4%), the user was unknown and the full popularity fallback applied.

This is item cold start caused by rapid news turnover, not an unexplained
model failure. A hybrid could add popularity per candidate, but it would
answer a different question from this pure collaborative baseline.

All three evaluations took about 2 minutes 51 seconds locally.

Implementation:
`src/recommender/ranking/baselines.py` and
`src/recommender/evaluation/evaluate_baseline.py`.
