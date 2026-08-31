# Data quality profile

This page summarizes the MIND-small training and development files after
ingestion to Parquet. The values come from a real run of
`src/recommender/data/profile.py`, not estimates. The generated local
report is ignored by Git.

## Main findings

| Finding | Why it matters |
|---|---|
| Most catalog articles are never shown in either window | Retrieval and coverage must use the full catalog as their denominator |
| Click-through rate is about 4% | Training labels are highly imbalanced |
| Most users interact once or twice | Sparse history and cold start are common |
| A few categories dominate the catalog | Diversity controls cannot assume balanced supply |
| Some fields are naturally missing | Missing history and abstracts are not automatically data defects |

## Scale

| | train | dev |
|---|---|---|
| news rows | 51,282 | 42,416 |
| behaviors rows | 156,965 | 73,152 |
| distinct users | 50,000 | 50,000 |
| distinct items impressed | 20,288 | 5,369 |
| item-impression pairs | 5,843,444 | 2,740,998 |

## Catalog exposure

Only 39.6% of training-window articles (20,288 of 51,282) receive an
impression. The development window exposes 12.7% (5,369 of 42,416).
Coverage metrics therefore use a catalog much larger than the articles
shown in one window.

## Click balance

Overall click-through rate is 4.04% for training and 4.06% for
development, or about one click per 25 shown items. The retrieval model
therefore uses explicit negative sampling instead of treating every
shown item equally during training.

## Impression size

Candidate counts range from 2 to 299. The mean is 37.2 in training and
37.5 in development; the median is 24 and 23. A small number of large
impressions raise the mean above the typical row.

## User activity

The median user has 2 interactions in training and 1 in development.
The maximum is 62 and 18. Most users therefore provide very little
history for personalization.

## Category distribution

There are 17 categories. `news` and `sports` make up 59.1% of
training-window articles and 58.5% of development-window articles.
Several categories have single-digit article counts. Reranking must
therefore handle uneven category supply.

## Structural integrity

Neither split contains duplicate `news_id` or `impression_id` values.
About 5% of articles have no abstract. Missing behavior history is 2.06%
in training and 3.03% in development; these rows represent users with
no prior clicks in the window.

## Click-through rate by category

`src/recommender/data/analytics.py` computes these values with DuckDB by
expanding impression items and joining them to the article catalog.
Category totals reproduce the overall counts and click rates above:
5,843,444 at 4.04% for training and 2,740,998 at 4.06% for development.

| category | train CTR | train rank | dev CTR | dev rank |
|---|---|---|---|---|
| music | 5.94% | 1 | 4.23% | 4 |
| tv | 5.90% | 2 | 4.41% | 3 |
| weather | 5.17% | 3 | 3.23% | 8 |
| sports | 4.76% | 4 | 7.44% | 1 |
| video | 4.55% | 5 | 3.21% | 9 |
| news | 4.36% | 6 | 4.02% | 5 |
| lifestyle | 4.06% | 7 | 5.22% | 2 |
| finance | 3.65% | 8 | 1.79% | 14 |
| health | 3.57% | 9 | 3.25% | 7 |
| movies | 3.17% | 11 | 3.08% | 10 |
| entertainment | 3.01% | 12 | 2.47% | 12 |
| foodanddrink | 2.95% | 13 | 3.30% | 6 |
| autos | 2.74% | 14 | 2.58% | 11 |
| travel | 2.64% | 15 | 1.95% | 13 |
| kids | 1.85% | 16 | 0.00% | 15 |

Catalog share and click rate are different signals. `music` and `tv`
have fewer impressions than `sports` or `news` but higher training
click rates. `sports` moves from fourth in training to first in
development, so a one-day category rank should not be treated as
stable.

Categories missing from the table had catalog articles but no
impressions in that window.

## Time coverage

Training spans November 9–14, 2019. Development is November 15, 2019.
The windows do not overlap. See [time-based splits](splits.md).
