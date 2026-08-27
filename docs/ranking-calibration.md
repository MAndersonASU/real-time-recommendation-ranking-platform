# Calibration and Score Inspection

AUC (`docs/ranking-model.md`) only measures whether the ranking model puts
clicked candidates above unclicked ones — it says nothing about whether a
predicted "8% chance of a click" happens roughly 8% of the time. This check
checks that separate property directly, plus the score distribution and
feature correlations, on real validation predictions from the trained
model. Implementation: `src/recommender/ranking/calibration.py`.

## Method

`calibration_bins` splits predictions into 10 equal-frequency groups
(`pandas.qcut`, not equal-width) and compares each group's mean predicted
probability against its actual observed click rate. Equal-frequency,
specifically, because with a ~4% overall click rate almost every
prediction is a small number clustered well under 0.5 — equal-width
buckets would leave most of them nearly empty. `expected_calibration_error`
reduces the table to one size-weighted number: the average gap between
predicted and observed across all ten groups.

## Results: calibration

| Decile | Mean predicted | Observed rate | Rows |
|---|---|---|---|
| 1 | 0.0188 | 0.0183 | 122,243 |
| 2 | 0.0252 | 0.0209 | 122,243 |
| 3 | 0.0285 | 0.0256 | 124,460 |
| 4 | 0.0308 | 0.0280 | 120,026 |
| 5 | 0.0335 | 0.0303 | 122,248 |
| 6 | 0.0365 | 0.0332 | 122,237 |
| 7 | 0.0402 | 0.0388 | 122,243 |
| 8 | 0.0455 | 0.0455 | 122,243 |
| 9 | 0.0544 | 0.0549 | 122,243 |
| 10 | 0.0925 | 0.0878 | 122,243 |

Expected calibration error: **0.0024** — every decile's predicted and
observed rates agree to within half a percentage point. This is the
direct payoff of the decision made while training
(`docs/ranking-model.md`) not to use class-weight balancing: an unweighted
fit on the true label distribution keeps predicted probabilities honest,
and this check confirms that held rather than just assuming it.

## Results: score distribution and feature correlations

Predicted probabilities across all 1,222,429 validation rows: mean 0.0406
(matching the ~3.83% validation click rate), std 0.0265, ranging from
0.00017 to 0.970 — a real, continuous spread, not a degenerate model that
collapses toward one value.

Pairwise correlations among the five model features, checked for any
near-duplicate pair that would make the model unstable or hide a shortcut:

| | retrieval_score | category_match | content_similarity | user_history_length | hour_of_day |
|---|---|---|---|---|---|
| retrieval_score | 1.000 | 0.352 | 0.221 | -0.001 | 0.041 |
| category_match | 0.352 | 1.000 | 0.222 | 0.053 | -0.016 |
| content_similarity | 0.221 | 0.222 | 1.000 | 0.276 | -0.015 |
| user_history_length | -0.001 | 0.053 | 0.276 | 1.000 | -0.008 |
| hour_of_day | 0.041 | -0.016 | -0.015 | -0.008 | 1.000 |

The highest correlation (0.352, `retrieval_score` vs `category_match`) is
expected and benign: both are partly derived from category-level signal,
and it's nowhere near the range that would indicate one feature is a
near-duplicate of another. Nothing here points to a hidden shortcut beyond
the one already found and removed (`popularity`) — the remaining five
features each contribute a distinct signal.
