# Ranking calibration

AUC measures ordering. Calibration asks a different question: when the
model predicts an 8% click probability, does a click occur about 8% of
the time?

This page checks calibration, score spread, and feature correlations on
real validation predictions. Implementation:
`src/recommender/ranking/calibration.py`.

## Method

`calibration_bins` divides predictions into ten groups with about the
same number of rows using `pandas.qcut`. Equal-width probability ranges
would be mostly empty because click probability is usually far below
0.5.

Each group compares mean predicted probability with observed click rate.
Expected calibration error is the row-weighted average of those gaps.

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

Expected calibration error is **0.0024**. Every group's prediction and
observed rate differ by less than half a percentage point.

This supports the [ranking model](ranking-model.md) choice not to use
class balancing. The unweighted fit stays close to the real label rate.

## Results: score distribution and feature correlations

Across 1,222,429 validation rows:

| Statistic | Value |
|---|---|
| Mean | 0.0406 |
| Standard deviation | 0.0265 |
| Minimum | 0.00017 |
| Maximum | 0.970 |

The mean is close to the 3.83% validation click rate, and the broad
range shows that the model does not collapse to one score.

Pairwise correlations check whether two inputs carry almost the same
signal:

| | retrieval_score | category_match | content_similarity | user_history_length | hour_of_day |
|---|---|---|---|---|---|
| retrieval_score | 1.000 | 0.352 | 0.221 | -0.001 | 0.041 |
| category_match | 0.352 | 1.000 | 0.222 | 0.053 | -0.016 |
| content_similarity | 0.221 | 0.222 | 1.000 | 0.276 | -0.015 |
| user_history_length | -0.001 | 0.053 | 0.276 | 1.000 | -0.008 |
| hour_of_day | 0.041 | -0.016 | -0.015 | -0.008 | 1.000 |

The largest value is 0.352 between `retrieval_score` and
`category_match`. Both include category information, but the
correlation is far from a near-duplicate. The five retained inputs carry
distinct signals; the known `popularity` shortcut is not present.
