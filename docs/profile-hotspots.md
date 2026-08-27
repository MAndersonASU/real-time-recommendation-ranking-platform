# Profiling Hotspots

Measures where the serving path actually spends memory, disk, and CPU
— not just wall-clock time per stage, which the per-stage latency
breakdown (`docs/serving-latency.md`) already covered.
Implementation: `src/recommender/monitoring/profile_hotspots.py`.

## Three measurements

- **Disk footprint** — the on-disk size of every artifact
  `ServingContext` loads: the two-tower model, the ranking model, the
  exact Faiss index.
- **Memory** — real process RSS (`psutil`), measured before and after
  `build_serving_context()`, not estimated from artifact sizes.
- **CPU vs. wall time** — `time.process_time()` alongside
 `time.perf_counter()` over real requests. Their divergence reveals
  something `docs/serving-latency.md`'s wall-clock-only numbers couldn't: whether a
 stage is computing, or using more than one CPU core at once
  underneath a single request.

## A real surprise: 515 MB of memory from artifacts under 7 MB combined

| Artifact | On-disk size |
|---|---|
| Two-tower model | 0.05 MB |
| Ranking model | ~0 MB |
| Faiss exact index | 6.26 MB |

`build_serving_context()`'s real RSS grew by **515 MB**, orders of
magnitude more than the artifacts it loads. Isolated line by line
against the real training split: `compute_popularity` and
`compute_first_seen` — two functions built independently, for the
baselines and for reranking, each for its own standalone use — **each call
`explode_impressions(train)` on their own**, fully re-exploding the
same ~4.6-million-row impression log a second and third time. The first
explosion (measured separately) cost ~237 MB; the second, inside
`compute_popularity`, cost another ~210 MB on top for data that already
existed once. This is measured, wasted duplication, not a guess —
and it's exactly the kind of evidence the optimization work
(`docs/optimization.md`) is scoped to act on, not this document, which is
scoped only to surface it.

## A second finding, relevant to load testing (`docs/load-test.md`)

Over 30 real requests, total CPU time (2.45s) came out to **4.8×**
total wall time (0.51s) — impossible for genuinely sequential,
single-threaded work. It means the numeric libraries underneath a
single request (PyTorch, NumPy's BLAS backend, Faiss) are already using
several CPU cores in parallel to hit their sub-millisecond-to-
low-millisecond stage times. That has a direct, disclosed implication
for load testing next: if one request already consumes multiple cores'
worth of compute, genuinely concurrent requests will contend hard for
the same limited CPU, and throughput won't necessarily scale the way a
single request's fast wall-clock time alone would suggest.
