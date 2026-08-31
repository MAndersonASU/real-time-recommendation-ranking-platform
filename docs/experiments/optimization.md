# Measured performance improvements

Profiling and load testing supported two changes:

- reuse one expanded impression table during startup; and
- limit PyTorch math to one thread per request.

## Reuse the expanded impression table

`build_serving_context` once expanded the same roughly 4.6-million-row
impression log three times through separate helper calls.

`compute_popularity` and `compute_first_seen` now accept an already
expanded `DataFrame`. Startup builds it once and shares it.

Measured on the same machine with `profile_hotspots.py`:

| | Before | After |
|---|---|---|
| RSS delta building a context | 515.1 MB | 448.1 MB |
| Context build time | 17.27 s | 11.9 s |

Startup became 31% faster and used 67 MB less additional resident
memory. The full test suite confirmed no behavior change.

## Use one PyTorch math thread

A single request consumed about five times its wall duration in CPU
time because PyTorch used several internal threads. Concurrent requests
then competed for the same cores.

`build_serving_context` now calls `torch.set_num_threads(1)` once. The
request pool controls concurrency instead of each request creating more
math threads.

Measured at concurrency 4:

| | Before | After |
|---|---|---|
| Throughput | 62.7 req/s | 78.8 req/s (**+26%**) |
| p50 latency | 61.3 ms | 49.8 ms (**−19%**) |

## Limit of the change

The thread limit helps at low and moderate concurrency. It does not add
CPU capacity. At concurrency 16, throughput changed from 72.8 to 67.2
requests per second; at 32, the difference was within measurement noise.

Smaller embeddings, quantization, or horizontal scaling were not added
because no measured traffic requirement justifies their complexity.

See the [hotspot profile](profile-hotspots.md) and
[historical load test](load-test.md).
