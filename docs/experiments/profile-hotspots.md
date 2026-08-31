# Historical performance profile

> This profile predates the documented optimizations and the current
> in-memory Faiss build. It explains why those changes were made; it is
> not a current resource profile.

Current values:

- context-build memory delta: 448.1 MB in
  [optimization](optimization.md); and
- request latency:
  [`reports/serving-latency.json`](../../reports/serving-latency.json).

Implementation:
`src/recommender/monitoring/profile_hotspots.py`.

## Measurements

| Resource | Method |
|---|---|
| Disk | File size of each artifact loaded by `ServingContext` at that time |
| Memory | Process RSS before and after `build_serving_context()` |
| CPU | `time.process_time()` compared with `time.perf_counter()` over real requests |

The disk list included a persisted exact Faiss index. The current
service rebuilds that index in memory and no longer loads this file.

## Artifact size versus memory

| Artifact | On-disk size |
|---|---|
| Two-tower model | 0.05 MB |
| Ranking model | ~0 MB |
| Faiss exact index | 6.26 MB |

Despite less than 7 MB of listed artifacts, context construction added
515 MB of RSS.

The cause was repeated expansion of the roughly 4.6-million-row
impression log:

- the first expansion used about 237 MB; and
- `compute_popularity` performed another expansion using about 210 MB.

`compute_first_seen` also expanded the same source independently.
Sharing one expanded table became the first optimization.

## CPU parallelism

Across 30 real requests:

| Measure | Value |
|---|---:|
| Total CPU time | 2.45 s |
| Total wall time | 0.51 s |
| CPU-to-wall ratio | 4.8× |

One request already used several cores through PyTorch, NumPy BLAS, and
Faiss. That predicted contention under concurrent traffic and motivated
the one-thread math configuration.

See [load test](load-test.md) and
[measured improvements](optimization.md).
