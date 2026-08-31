# Historical load test

> This is a pre-optimization result. It is retained because it exposed
> CPU saturation. It is not the current latency profile.

The later single-math-thread configuration increased concurrency-4
throughput from 62.7 to 78.8 requests per second, a 26% gain. Retrieval
depth and cold-start behavior also changed afterward.

Use [serving latency](serving-latency.md) for the current request profile.

`src/recommender/monitoring/load_test.py` sends real concurrent calls to
`safe_recommend` and records throughput, percentiles, and errors.

## A thread pool, not a process pool

`run_load_test` uses `ThreadPoolExecutor`. Threads share one process's
CPU resources and expose contention between simultaneous requests.
Separate worker processes would change the resource model being tested.

## Results: throughput never rises, latency scales almost linearly

| Concurrency | Throughput (req/s) | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 71.4 | 14 ms | 16 ms | 42 ms |
| 4 | 62.7 | 61 ms | 82 ms | 100 ms |
| 8 | 68.8 | 114 ms | 140 ms | 154 ms |
| 16 | 72.8 | 210 ms | 270 ms | 302 ms |
| 32 | 74.1 | 391 ms | 501 ms | 596 ms |

Zero errors at every level tested.

## Interpretation

Throughput stays near 62–74 requests per second while median latency
rises from 14 ms to 391 ms. More concurrent requests create waiting but
do not increase completed work.

The machine has 8 logical CPUs. The earlier profile measured one
request's CPU time at 4.8 times its wall time because PyTorch, NumPy
BLAS, and Faiss all used internal parallelism. A small number of
simultaneous requests could therefore consume the available cores.

This result motivated limiting math-library threads. See
[optimization](optimization.md) and the
[historical hotspot profile](profile-hotspots.md).
