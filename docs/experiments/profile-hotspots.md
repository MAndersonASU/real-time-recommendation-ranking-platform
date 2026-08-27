# Profiling Hotspots

**Historical, pre-optimization measurement.** Dated before the fix
described in `docs/experiments/optimization.md`, and before the Faiss
index changed from a persisted, on-disk artifact to one rebuilt in
memory at every startup (`docs/architecture.md`). The disk-footprint
table below therefore lists an artifact `ServingContext` no longer
loads from disk at all, and the 515 MB memory figure is the *before*
number the optimization work measured itself against -- the current,
fixed figure (448.1 MB) is in `docs/experiments/optimization.md`, and
current request latency is in
[`reports/serving-latency.json`](../../reports/serving-latency.json).
Kept here as the profiling methodology and the finding that motivated
the fix, not as a current measurement of `ServingContext` as it exists
now.

Measures where the serving path actually spends memory, disk, and CPU
— not just wall-clock time per stage, which the per-stage latency
breakdown (`docs/experiments/serving-latency.md`) already covered.
Implementation: `src/recommender/monitoring/profile_hotspots.py`.

## Three measurements

- **Disk footprint** — the on-disk size of every artifact
  `ServingContext` loaded at the time of this measurement: the
  two-tower model, the ranking model, and the then-persisted exact
  Faiss index (no longer a disk-loaded artifact today; see the notice
  above).
- **Memory** — real process RSS (`psutil`), measured before and after
  `build_serving_context()`, not estimated from artifact sizes.
- **CPU vs. wall time** — `time.process_time()` alongside
 `time.perf_counter()` over real requests. Their divergence reveals
something `docs/experiments/serving-latency.md`'s wall-clock-only
numbers couldn't: whether a stage is computing, or using more than one
CPU core at once underneath a single request.

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
(`docs/experiments/optimization.md`) is scoped to act on, not this
document, which is scoped only to surface it.

## A second finding, relevant to load testing (`docs/experiments/load-test.md`)

Over 30 real requests, total CPU time (2.45s) came out to **4.8×**
total wall time (0.51s) — impossible for genuinely sequential,
single-threaded work. It means the numeric libraries underneath a
single request (PyTorch, NumPy's BLAS backend, Faiss) are already using
several CPU cores in parallel to hit their
sub-millisecond-to-low-millisecond stage times. That has a direct,
disclosed implication for load testing next: if one request already
consumes multiple cores' worth of compute, genuinely concurrent requests
will contend hard for the same limited CPU, and throughput won't
necessarily scale the way a single request's fast wall-clock time alone
would suggest.
