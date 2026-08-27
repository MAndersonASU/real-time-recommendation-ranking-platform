# Optimizing Justified Bottlenecks

Two real fixes, each directly justified by evidence from
`docs/profile-hotspots.md` and `docs/load-test.md` — nothing here was
optimized on a hunch, and nothing was optimized that the evidence
didn't actually point to.

## Fix 1: share one exploded impression log instead of three

`compute_popularity` (the baselines) and `compute_first_seen` (reranking) were
each written independently, at different times, for their own
standalone use — and each called `explode_impressions(train)` on its
own. `build_serving_context` called both, so the same ~4.6-million-row
impression log was fully re-exploded three times over. Both functions
now accept an optional, already-exploded `DataFrame`; `build_serving_context` explodes once and passes the same frame to both.

**measured before/after** (`profile_hotspots.py`, same machine,
same run conditions):

| | Before | After |
|---|---|---|
| RSS delta building a context | 515.1 MB | 448.1 MB |
| Context build time | 17.27 s | 11.9 s |

A smaller memory saving than the naive per-explosion cost would
suggest — Python's own allocator reuses some of that space between the
duplicate calls — but the build-time improvement is unambiguous: **31%
faster**, with zero behavior change, verified by the full test suite
passing unchanged.

## Fix 2: cap PyTorch to one thread per math operation

Profiling found a single request's CPU time at roughly 5× its own wall
time — PyTorch spreading one request's math across several threads by
default. The load test then showed throughput never rising with
concurrency, exactly what thread oversubscription under real
concurrent load looks like. `build_serving_context` now calls
`torch.set_num_threads(1)` once, for the whole process — since this
process expects to serve many concurrent requests, not minimize one
request's isolated wall time, leaving concurrency entirely to the
request-level thread pool is the right tradeoff.

**measured before/after**, same load test, concurrency 4 (the
level with the clearest signal):

| | Before | After |
|---|---|---|
| Throughput | 62.7 req/s | 78.8 req/s (**+26%**) |
| p50 latency | 61.3 ms | 49.8 ms (**−19%**) |

## What the evidence does *not* justify fixing here

The fix helps at low-to-moderate concurrency but does not move this
machine's fundamental 8-core ceiling: at concurrency 16, throughput is
effectively unchanged (67.2 vs. 72.8 req/s) and at 32 it's within noise
of the unfixed baseline. Going further — smaller embeddings, quantized
inference, or actually scaling horizontally across more processes or
machines — is real work with a cost, and nothing measured so far
demonstrates this project's traffic ever needs it. That's exactly why
it isn't attempted here: the evidence justifies these two fixes, and
stops justifying anything past them.
