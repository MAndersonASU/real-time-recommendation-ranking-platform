# Durable-history fallback evaluation

Source:
[`reports/durable-history-fallback.json`](../../reports/durable-history-fallback.json).

This evaluation isolates the serving path used when a returning user has
saved history but Redis has no usable recent clicks.

Implementation:
`src/recommender/evaluation/evaluate_durable_history_fallback.py`.
Tests: `tests/test_evaluate_durable_history_fallback.py`.

## Problem and correction

Before `SERVING-DURABLE-HISTORY-69`, the retrieval query used only
`recent_clicked_items` from Redis. A user with durable history and an
empty Redis record therefore received global-popularity candidates.

A direct six-user reproduction produced only 3 distinct top-10 slates
and 10 distinct articles.

`select_retrieval_history` now chooses exactly one source:

1. usable recent Redis clicks;
2. bounded durable history; or
3. global popularity when neither exists.

Recent and durable histories are not merged because the project has no
validated rule for overlap, duplicate clicks, or ordering between them.
`retrieval_history_source` reports which source was used.

## Why this evaluation is separate

The normal end-to-end evaluation reconstructs recent state from each
impression's point-in-time history and has 97.6% recent-feature
coverage. It rarely reaches the empty-Redis, durable-only path.

This evaluation uses:

- real validation impressions;
- point-in-time durable history;
- the real `safe_recommend()` path; and
- a new isolated `InMemoryRedis` that is never seeded or written.

An impression qualifies only when its point-in-time history contains at
least one article available in the content catalog. Empty or entirely
off-catalog history is excluded and counted.

## Result

The seeded sample contains 8,000 validation impressions. Of those, 7,790
qualify and represent 6,885 users.

| Metric | Result |
|---|---|
| Eligible impressions evaluated | 7,790 (of 8,000 sampled; 210 excluded) |
| Eligible users | 6,885 |
| Retrieval history source | 100% durable (7,790 of 7,790) |
| Distinct top-10 sets | 7,312 |
| Distinct recommended items | 7,780 |
| Catalog coverage@10 | 15.2% |
| Top-10 concentration | 0.10% |
| Mean pairwise slate Jaccard | 6.3% |
| Retrieval contained a click | 13.7% |
| Hit rate@10 | 0.81% |
| Recall@10 | 0.51% |
| NDCG@10 | 0.40% |
| MRR | 0.46% |

A regression test requires all 7,790 eligible requests to report
`retrieval_history_source="durable"`. This prevents recent data from
silently entering the isolated cohort.

## What is and is not compared

This is a post-correction evaluation only. It does not contain a
large-scale pre-correction arm on the same 7,790 impressions.

Pre-correction behavior is supported by:

- the older code, which had no durable fallback; and
- the direct six-user reproduction.

Those facts establish the mechanism but are not a representative quality
baseline. A stronger comparison would run the old and new code on the
same cohort and record both the full retrieval pools and final slates.

`distinct_top_k_sets` and `catalog_coverage_at_k` refer to the final
served top 10 after ranking and reranking. They do not measure diversity
across the roughly 1,000 retrieved candidates.

## Interpretation

Durable-only requests now produce 7,312 distinct served slates instead
of one shared popularity result. The fallback is personalized and
measurably varied.

Relevance remains low. The clicked article reaches retrieval in 13.7%
of requests and the final top 10 in 0.81%. The evaluation does not claim
that durable history is as useful as recent live clicks.

Other limits:

- MIND history is bounded and may not represent a user's complete real
  history;
- the isolated design does not show how often production users take
  this path;
- the run does not represent production traffic, concurrency, or
  infrastructure latency; and
- ranking cannot recover a clicked article that retrieval did not
  surface.

See [end-to-end evaluation](serving-path-end-to-end-evaluation.md) and
[review finding SERVING-DURABLE-HISTORY-69](../engineering-review-register.md).
