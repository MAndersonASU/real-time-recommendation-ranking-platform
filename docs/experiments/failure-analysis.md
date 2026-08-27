# Failure Case Analysis

Generated from [`reports/failure-analysis.json`](../../reports/failure-analysis.json).

Every metric reported so far is one aggregate number across 30,270
validation impressions. This document segments the misses themselves:
for each real impression the frozen K=10 evaluation protocol already
scores, whether the real click landed in the reranked top-10 slate,
grouped by three properties already computed as real ranking-model
input features. Implementation:
`src/recommender/evaluation/failure_analysis.py`.

## Results: overall

30,270 impressions analyzed, the identical reranked served slate
every other evaluation in this project scores. **Overall miss rate:
33.2%** (consistent with the tracked hit rate of 0.6675 for the reranked
system, `docs/experiments/reranking-evaluation.md`).

## By user history length

| History length | Impressions | Miss rate |
|---|---|---|
| 0 (cold-start user) | 772 | 43.5% |
| 1-5 | 4,411 | 36.1% |
| 6-20 | 10,405 | 33.1% |
| 20+ | 14,682 | 31.9% |

Monotonic and unsurprising: the less history a user has, the more often
the system misses. Consistent with every earlier finding about sparse
per-user history in this dataset (`docs/experiments/data-quality.md`) and with
the online feature store's own disclosed asymmetry between offline and online history
depth.

## By clicked-item coldness

| | Impressions | Miss rate |
|---|---|---|
| Cold item (never clicked in train) | 20,486 | 27.7% |
| Warm item (clicked at least once in train) | 9,784 | 44.8% |

**A real, counter-intuitive result, checked rather than reported
blindly**: cold items miss *less* often than warm ones, the opposite of
the naive expectation that an unseen item should be harder to recommend.
Checked directly: the ranking model's own mean predicted score for the
actually-clicked item is nearly identical either way (0.0560 warm vs.
0.0554 cold) — the model itself does not treat cold and warm clicked
items differently, consistent with `popularity` being excluded from its
inputs entirely (`docs/experiments/ranking-model.md`). The real explanation is
impression size: impressions where the real click lands on a warm item
average **50.8 competing candidates**, versus **35.4** for a cold-item
click — a warm item is more often clicked in an impression that is
itself larger and more competitive, diluting its odds of landing in the
top 10 purely by having more rivals for the same 10 slots, not because
the model scores it worse.

## By category match with user history

| | Impressions | Miss rate |
|---|---|---|
| Clicked item's category matched the user's dominant history category | 8,346 | 28.3% |
| Did not match | 21,924 | 35.1% |

A real, expected gap: `category_match` is one of the ranking model's own
input features, so a click that agrees with the model's own signal
should be, and is, easier to place in the top 10.

## What this adds beyond the aggregate number

An overall hit rate says the system works roughly two-thirds of the
time; it says nothing about which third it fails. The clearest, most
actionable segment here is user history length: a genuinely new user
misses 11.6 percentage points more often than a well-established one,
a concrete, quantified argument for where a future improvement (a
stronger cold-start policy, not a general model change) would help
most, feeding directly into the conclusions this component closes with.
