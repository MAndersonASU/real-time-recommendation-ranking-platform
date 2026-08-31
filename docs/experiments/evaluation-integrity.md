# Evaluation integrity

Early work used `validation` both to make three design choices and to
report their results. No gradient training used validation, but choosing
a feature or policy from its measurements still makes later validation
results post-selection development evidence.

The affected choices were:

- excluding `popularity` from the ranking model;
- setting the diversity category cap to 3; and
- setting the freshness threshold to 12 hours with a quota of 2.

No untouched final split remains. This page explains the separate tuning
fold used for later decisions and what its checks found.

## Tuning-fold design

`src/recommender/evaluation/tuning_fold.py` divides `train` by
`impression_id` so candidates from one impression stay together. The
split is seeded and deterministic.

`src/recommender/evaluation.verify_tuning_decisions` refits the required
models on the fit portion and evaluates alternatives on the tuning
portion. Validation is not used.

This infrastructure prevents new selection leakage. It cannot turn older
validation results into final estimates.

## Recheck of the original policy evidence

Source: [`reports/tuning-decisions.json`](../../reports/tuning-decisions.json).

| Decision | Original (validation) | Tune fold | Confirmed? |
|---|---|---|---|
| Diversity: 4+ same-category rate | 53.1% | 56.6% | Yes — same order of magnitude, same conclusion |
| Diversity: single-category rate | 4.6% | 5.2% | Yes |
| Freshness: fresh-row rate at 12h | 36.3% | 32.3% | Yes — same order of magnitude |
| Freshness: zero-fresh-impression rate | 0.7% | 3.4% | Yes — still rare, same conclusion |

The separate fold supports the category-concentration and 12-hour
freshness observations.

## Why popularity behaved differently

Popularity alone had AUC 0.47 on the later validation day but 0.665 on a
random tuning split:

| | Original (validation) | Random-split tune fold |
|---|---|---|
| Popularity-alone AUC | 0.47 (worse than random) | 0.665 (clearly better than random) |

The random split can place nearby times on opposite sides. Short-term
popularity may then carry across the boundary. A chronological split
uses the earliest 80% for fit and the latest 20% for tuning:

| | Original (validation) | Random-split tune fold | Chronological-split tune fold |
|---|---|---|---|
| Popularity-alone AUC | 0.47 | 0.665 | **0.489** |

The chronological result is close to validation and supports a recency
explanation. It does not prove recency is the only cause because a
chronological split also changes which users and impressions appear on
each side.

Popularity remains excluded. The random split remains suitable for
diversity and freshness checks; the chronological split is used for
time-sensitive questions.

## Freshness threshold alternatives

The rule was fixed before viewing the alternatives: select the smallest
threshold for which fewer than 5% of impressions have no fresh
candidate.

| Threshold (days) | Fresh-row rate | Zero-fresh-impression rate |
|---|---|---|
| 0.25 | 12.2% | 23.5% |
| **0.5 (configured)** | **32.3%** | **3.4%** |
| 1.0 | 73.0% | 0.1% |
| 2.0 | 88.5% | ~0.0% |
| 7.0 | 100% | 0.0% |

The rule independently selects 0.5 days, or 12 hours.

## Diversity-cap alternatives

The first rule compared diversity benefit with the uncapped slate. It
could not distinguish values because tighter caps always increase that
benefit.

The replacement rule asks a real tradeoff question: among caps that
retain a required share of uncapped predicted relevance, choose the one
with the most distinct categories.

| Cap | Mean slate relevance | Mean distinct categories |
|---|---|---|
| 1 | 0.498 | 7.52 |
| 2 | 0.552 | 5.69 |
| **3 (configured)** | **0.579** | **5.07** |
| 5 | 0.602 | 4.57 |
| No cap | 0.614 | 4.24 |

Different relevance budgets select different caps:

| Relevance budget | Cap selected |
|---|---|
| 85% | 2 |
| 90% | **3 (the configured value)** |
| 95% | 5 |
| 99% | none affordable |

Cap 3 follows from a 90% predicted-relevance budget. The data does not
determine which budget a product should prefer.

## Retrieval-depth alternatives

The older service retrieved 50 candidates. The tuning fold measured
clicked-item containment and Faiss search latency at larger depths:

| Depth | Clicked item reached the ranker | Search p99 |
|---|---|---|
| 50 (was configured) | 6.2% | 0.34 ms |
| 100 | 9.3% | 0.39 ms |
| 200 | 11.9% | 0.47 ms |
| 500 | 15.8% | 0.78 ms |
| **1000 (now configured)** | **21.5%** | **2.27 ms** |

Every tested depth stayed under the predefined 5 ms Faiss-search
budget, so that budget did not select a unique value. End-to-end
measurement found that depth 1,000 adds about 4 ms median request
latency over depth 50.

Depth 1,000 was chosen as a documented judgment: about 3.6× more clicks
reached the ranker for about 4 ms. It was not presented as the automatic
output of a rule.

## Current interpretation

| Decision | Evidence |
|---|---|
| Freshness threshold, 12 hours | Reconfirmed by a predefined coverage rule |
| Diversity cap, 3 | Selected by a 90% predicted-relevance budget; the budget is a product choice |
| Retrieval depth, 1,000 | Chosen from a measured containment-latency tradeoff |
| Popularity exclusion | Supported by the chronological check, with user-composition confounding still disclosed |

The minimum-fresh quota needed a stronger, click-based experiment. Its
[protocol](min-fresh-experiment-protocol.md) was frozen before the run.

## General rule

A selection rule must be able to reject at least one candidate value.
Rules that only reward a quantity that moves monotonically with the
parameter will always choose an edge of the tested range.

Useful rules bound the cost of a desired gain, such as relevance lost
for diversity or latency spent for greater containment. If the bound
does not exclude anything, the final choice should be recorded as
judgment rather than described as data-selected.
