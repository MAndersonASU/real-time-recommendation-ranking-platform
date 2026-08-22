# Load Testing the Service

Generates real concurrent traffic against the real `safe_recommend`
path and measures throughput, latency percentiles, error rate, and
saturation — not against a mocked or simplified stand-in.
Implementation: `src/recommender/monitoring/load_test.py`.

## A thread pool, not a process pool

`run_load_test` uses `ThreadPoolExecutor`, not multiprocessing. Python
threads share one process's real CPU budget, so a thread pool actually
exercises the CPU contention `docs/profile-hotspots.md` found
underneath a single request. A process pool would hand each concurrent
request its own separate resource allocation illusion and hide exactly
the contention this test needs to surface.

## Real result: throughput never rises, latency scales almost linearly

| Concurrency | Throughput (req/s) | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 | 71.4 | 14 ms | 16 ms | 42 ms |
| 4 | 62.7 | 61 ms | 82 ms | 100 ms |
| 8 | 68.8 | 114 ms | 140 ms | 154 ms |
| 16 | 72.8 | 210 ms | 270 ms | 302 ms |
| 32 | 74.1 | 391 ms | 501 ms | 596 ms |

Zero errors at every level tested.

## The saturation point was already reached at concurrency 1

Throughput is flat — roughly 62–74 requests per second regardless of
how many concurrent requests are in flight — while p50 latency scales
almost perfectly linearly with concurrency (14 → 61 → 114 → 210 →
391 ms, each step tracking the concurrency multiplier closely). That is
the textbook signature of a CPU-bound system that is already saturated:
adding more concurrent work doesn't produce more completed work per
second, it only makes every request wait longer for the same fixed
amount of CPU.

This machine has **8 logical CPUs**. `docs/profile-hotspots.md` measured
a single request's CPU time at **4.8× its own wall time** — meaning one
request alone already uses close to five cores' worth of parallel
compute (PyTorch, NumPy's BLAS backend, and Faiss all parallelizing
internally). Two requests running at once already approach this
machine's full 8-core budget; by four or more, it's fully saturated.
This isn't a new, separate finding — it's the profiling result from the
previous step, now confirmed under real concurrent load exactly as it
predicted.
