# Data Quality Profile

Concise EDA over the ingested MIND-small train/dev splits, scoped to the
measurements later phases actually depend on rather than a general
exploration. Methodology: `src/recommender/data/profile.py`, run against
the Step 1.2 Parquet output. The report itself is a local, gitignored,
reproducible artifact — the findings below are transcribed from an actual
run, not estimated.

## Scale

| | train | dev |
|---|---|---|
| news rows | 51,282 | 42,416 |
| behaviors rows | 156,965 | 73,152 |
| distinct users | 50,000 | 50,000 |
| distinct items impressed | 20,288 | 5,369 |
| item-impression pairs | 5,843,444 | 2,740,998 |

## Catalog coverage

Most of the news catalog available in a given window is never actually
shown: only 39.6% of train-window articles (20,288 of 51,282) receive at
least one impression; dev is more extreme at 12.7% (5,369 of 42,416).
Candidate retrieval (Phase 3) and coverage metrics need to account for a
catalog far larger than what any single window's impressions exercise.

## Click balance

Overall click-through rate: 4.04% (train), 4.06% (dev) — roughly one click
per 25 impressed items. Confirms the severe class imbalance a retrieval or
ranking model trained on raw impression labels will face, and directly
motivates Phase 3's explicit negative-sampling design rather than training
on every impressed item as-is.

## Impression size

Candidates per impression: min 2, max 299, mean 37.2 (train) / 37.5 (dev),
median 24 (train) / 23 (dev). The gap between mean and median is a
right-skewed distribution — a small number of unusually large impressions
pull the mean above the typical case.

## User activity

Interactions per user: median 2 (train) / 1 (dev), max 62 (train) / 18
(dev). Most users in a given window interact only once or twice — direct
evidence for how thin per-user history typically is, relevant to Phase 7's
cold-start handling.

## Category distribution

17 categories, heavily concentrated: `news` and `sports` alone account for
59.1% of train-window articles (58.5% in dev). The remaining 15 categories
share the rest, several (`kids`, `middleeast`, and one of `northamerica`/
`games` depending on the window) with single-digit counts. Phase 5's
diversity control needs to account for this imbalance rather than assume a
roughly even category split.

## Structural integrity

Zero duplicate `news_id` or `impression_id` in either split. Null rates:
`news.abstract` ~5% in both splits (expected — some articles ship without
an abstract); `behaviors.history` 2.06% (train) / 3.03% (dev) — cold-start
users with no prior clicks in-window, not a data defect.

## Time coverage

Train spans 2019-11-09 through 2019-11-14; dev is exactly 2019-11-15 (a
single day). The official split is already a clean, non-overlapping date
boundary, useful context for Step 1.5's leakage-safe splits.
