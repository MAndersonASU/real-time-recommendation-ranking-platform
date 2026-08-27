# Data Quality Profile

Concise EDA over the ingested MIND-small train/dev splits, scoped to the
measurements later work depends on rather than a general
exploration. Methodology: `src/recommender/data/profile.py`, run against
the ingestion pipeline's Parquet output (`src/recommender/data/ingest.py`).
The report itself is a local, gitignored, reproducible artifact — the
findings below are transcribed from an actual run, not estimated.

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
Candidate retrieval (the retrieval model) and coverage metrics need to account for a
catalog far larger than what any single window's impressions exercise.

## Click balance

Overall click-through rate: 4.04% (train), 4.06% (dev) — roughly one click
per 25 impressed items. Confirms the severe class imbalance a retrieval or
ranking model trained on raw impression labels will face, and directly
motivates the retrieval model's explicit negative-sampling design rather than training
on every impressed item as-is.

## Impression size

Candidates per impression: min 2, max 299, mean 37.2 (train) / 37.5 (dev),
median 24 (train) / 23 (dev). The gap between mean and median is a
right-skewed distribution — a small number of unusually large impressions
pull the mean above the typical case.

## User activity

Interactions per user: median 2 (train) / 1 (dev), max 62 (train) / 18
(dev). Most users in a given window interact only once or twice — direct
evidence for how thin per-user history typically is, relevant to the online feature store's
cold-start handling.

## Category distribution

17 categories, heavily concentrated: `news` and `sports` alone account for
59.1% of train-window articles (58.5% in dev). The remaining 15 categories
share the rest, several (`kids`, `middleeast`, and one of `northamerica`/
`games` depending on the window) with single-digit counts. reranking's
diversity control needs to account for this imbalance rather than assume a
roughly even category split.

## Structural integrity

Zero duplicate `news_id` or `impression_id` in either split. Null rates:
`news.abstract` ~5% in both splits (expected — some articles ship without
an abstract); `behaviors.history` 2.06% (train) / 3.03% (dev) — cold-start
users with no prior clicks in-window, not a data defect.

## Click-through rate by category

Computed directly against the Parquet files with DuckDB (`src/recommender/data/analytics.py`) — a CTE unnests the impression log, joins back to `news` on `news_id`, and ranks categories by CTR with a window function. The category-level totals sum to the same overall CTR already reported above (train: 5,843,444 impressions, 4.04%; dev: 2,740,998, 4.06%), a cross-check between two independent tools computing the same underlying number.

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

Two things worth noting rather than smoothing over: category share of the
catalog (news/sports dominate, above) and category CTR are not the same
signal — `music` and `tv` have far fewer impressions than `sports` or
`news` but convert at a noticeably higher rate in train. And `sports`
swings from rank 4 (train) to rank 1 (dev), a reminder that a single
6-day training window and a single dev day are both small enough for
per-category rates to move — not a claim that any one day's ranking is a
stable property of the category itself. A handful of categories present
in `news.tsv` (`middleeast`, and `northamerica`/`games` depending on the
window) don't appear in this table at all: consistent with the catalog
coverage finding above, those articles were never impressed to any user in
that window.

## Time coverage

Train spans 2019-11-09 through 2019-11-14; dev is exactly 2019-11-15 (a
single day). The official split is already a clean, non-overlapping date
boundary, useful context for the leakage-safe time-aware splits
(`docs/splits.md`).
