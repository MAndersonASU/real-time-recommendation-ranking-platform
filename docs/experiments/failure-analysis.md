# Candidate-list failure analysis

Source:
[`reports/failure-analysis.json`](../../reports/failure-analysis.json).

This report groups misses from the frozen K=10 reranking evaluation by
user history, clicked-item training history, and category match.

It analyzes MIND's supplied candidate lists. It does not describe
end-to-end serving misses from full-catalog retrieval.

Implementation:
`src/recommender/evaluation/failure_analysis.py`.

## Overall result

The analysis covers all 30,270 validation impressions. The miss rate is
33.3%, consistent with candidate-list hit rate@10 of 0.6675.

## User history

| History length | Impressions | Miss rate |
|---|---|---|
| 0 (cold-start user) | 772 | 43.9% |
| 1-5 | 4,411 | 35.3% |
| 6-20 | 10,405 | 33.1% |
| 20+ | 14,682 | 32.2% |

Miss rate falls as more user history becomes available. A user with no
history misses 11.7 percentage points more often than a user with more
than 20 history items.

## Clicked-item training history

| | Impressions | Miss rate |
|---|---|---|
| Cold item (never clicked in train) | 20,486 | 27.6% |
| Warm item (clicked at least once in train) | 9,784 | 45.0% |

Warm clicked items miss more often, which at first appears
counterintuitive. The ranker's mean score for the clicked item is almost
the same:

| Clicked item | Mean predicted score | Mean candidates in impression |
|---|---:|---:|
| Warm | 0.0560 | 50.8 |
| Cold | 0.0554 | 35.4 |

The larger warm-item impressions create more competition for the same
10 positions. The model does not directly use popularity, so it does not
otherwise favor a training-clicked item.

## Category match

| | Impressions | Miss rate |
|---|---|---|
| Clicked item's category matched the user's dominant history category | 8,346 | 28.7% |
| Did not match | 21,924 | 35.0% |

This direction is expected because `category_match` is a ranker input.

## Main takeaway

Within the supplied-candidate protocol, missing user history is the
clearest weak segment. That supports work on a stronger cold-start
policy.

Do not turn the 66.75% candidate-list hit rate into a claim that the
complete system succeeds two-thirds of the time. The
[end-to-end evaluation](serving-path-end-to-end-evaluation.md) reports
the full serving result separately.
