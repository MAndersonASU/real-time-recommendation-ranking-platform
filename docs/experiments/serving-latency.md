# Serving latency by operation

Source:
[`reports/serving-latency.json`](../../reports/serving-latency.json).

This report times the real `recommend()` path with an optional
`stage_timings` dictionary. When timing is not requested, the normal
path keeps only the small `perf_counter()` call cost.

Measurement command:
`src/recommender/serving/verify_latency.py`.

## Current result

The run uses 100 validation users selected uniformly with a fixed seed.
Redis runs in a container. Artifacts match the
[build receipt](../../provenance/build-receipt.json).

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Reranking (diversity + freshness) | **10.63 ms** | **14.28 ms** | **15.55 ms** |
| Feature building (category/content-similarity) | 6.86 ms | 7.64 ms | 8.08 ms |
| Ranking (logistic regression) | 1.70 ms | 2.01 ms | 2.04 ms |
| Feature lookup (the online feature store) | 1.12 ms | 1.42 ms | 5.75 ms |
| Candidate retrieval | 0.86 ms | 3.61 ms | 16.54 ms |
| User embedding (two-tower forward pass) | 0.34 ms | 0.49 ms | 0.57 ms |
| **Total** | 21.78 ms | 27.21 ms | 52.79 ms |

Reranking, at 10.63 ms median, is now the largest stage. Its duplicate
check compares candidates with already selected items, creating a
roughly quadratic cost as candidate count grows.

Candidate retrieval has a long tail: 0.86 ms median and 16.54 ms p99.
Users with neither recent nor durable history use a full-catalog
popularity sort, which is slower than Faiss search.

The total median is not the sum of operation medians. Each percentile is
calculated independently across requests.

## Change after durable-history fallback

Median total latency fell from 31.44 ms to 21.78 ms after
`SERVING-DURABLE-HISTORY-69`. Candidate retrieval fell from 13.11 ms to
0.86 ms because returning users with durable history now use Faiss
instead of the expensive popularity path.

Reranking did not become slower because of that correction. It became
the largest operation because retrieval became much faster.

<details>
<summary>August 27 measurement before durable-history fallback</summary>

The sampling method matches the current run.

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Candidate retrieval | 13.11 ms | 15.03 ms | 16.58 ms |
| Reranking (diversity + freshness) | 9.89 ms | 11.65 ms | 12.59 ms |
| Feature building (category/content-similarity) | 5.13 ms | 5.79 ms | 6.33 ms |
| Feature lookup (the online feature store) | 1.24 ms | 1.56 ms | 22.05 ms |
| Ranking (logistic regression) | 1.73 ms | 2.39 ms | 2.51 ms |
| User embedding (two-tower forward pass) | 0.40 ms | 0.59 ms | 0.73 ms |
| **Total** | 31.44 ms | 34.89 ms | 56.86 ms |

</details>

## Why sampling changed

An older implementation used the first 100 distinct users in file
order. It now uses a seeded uniform sample.

With the same pipeline, that change moved total median from 21.31 ms to
31.44 ms. User history and fallback path affect the amount of work, so
the first users were not representative.

<details>
<summary>August 26 first-100-users measurement</summary>

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Candidate retrieval | 8.78 ms | 10.27 ms | 12.65 ms |
| Reranking (diversity + freshness) | 6.36 ms | 8.58 ms | 12.35 ms |
| Feature building (category/content-similarity) | 3.16 ms | 4.31 ms | 6.72 ms |
| Feature lookup (the online feature store) | 1.32 ms | 1.67 ms | 21.97 ms |
| Ranking (logistic regression) | 1.07 ms | 1.49 ms | 2.05 ms |
| User embedding (two-tower forward pass) | 0.31 ms | 0.53 ms | 0.59 ms |
| **Total** | 21.31 ms | 25.35 ms | 60.97 ms |

</details>

## Older pipeline measurement

The August 21 pipeline retrieved 50 candidates and had no explicit
cold-start popularity path. Its numbers are historical and should not be
averaged with the current pipeline.

<details>
<summary>August 21 measurement</summary>

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Feature lookup (the online feature store) | 0.75 ms | 1.07 ms | 1.77 ms |
| User embedding (two-tower forward pass) | 0.30 ms | 0.46 ms | 0.68 ms |
| Candidate retrieval (Faiss) | 0.22 ms | 0.38 ms | 1.03 ms |
| Feature building (category/content-similarity) | 0.58 ms | 1.21 ms | 1.82 ms |
| Ranking (logistic regression) | 1.49 ms | 2.92 ms | 3.63 ms |
| Reranking (diversity + freshness) | 8.88 ms | 11.06 ms | 12.24 ms |
| **Total** | 12.79 ms | 14.96 ms | 17.09 ms |

</details>

Retrieval depth increased from 50 to 1,000 on August 24. The larger pool
also increases downstream ranking and reranking work.

## Limits

The run uses one developer machine and a local container stack. Absolute
latency depends on CPU, container limits, Redis location, and current
machine load. It is not a production service-level claim.

See [inference path](../operations/inference-path.md),
[diversity reranking](reranking-diversity.md), and
[evaluation integrity](evaluation-integrity.md).
