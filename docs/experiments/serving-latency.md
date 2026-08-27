# Latency By Stage

Measures where a real request's time actually goes, stage by stage, not
just the one end-to-end number the inference path already produced
(`docs/operations/inference-path.md`). Implementation:
`recommend()`'s optional `stage_timings` parameter in
`src/recommender/serving/pipeline.py`; measurement script
`src/recommender/serving/verify_latency.py`. Machine-readable result:
[`serving-latency.json`](../../reports/serving-latency.json).

## One code path, opt-in instrumentation

`recommend()` takes an optional `stage_timings` dict. When one is passed,
every stage records its own elapsed time into it; when it's left `None`
(the default, and what every earlier component's tests and verification
already call), a request pays only the cost of a few no-op
`perf_counter()` checks. This measures the actual runtime code path
directly, rather than a second, separately maintained timing harness
that could quietly drift out of sync with what really executes.

## Current measurement, 100 real validation users, six stages

Against a containerized Redis, on the artifact bundle recorded in
[`build-receipt.json`](../../provenance/build-receipt.json).

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Candidate retrieval | **8.78 ms** | **10.27 ms** | **12.65 ms** |
| Reranking (diversity + freshness) | 6.36 ms | 8.58 ms | 12.35 ms |
| Feature building (category/content-similarity) | 3.16 ms | 4.31 ms | 6.72 ms |
| Feature lookup (the online feature store) | 1.32 ms | 1.67 ms | 21.97 ms |
| Ranking (logistic regression) | 1.07 ms | 1.49 ms | 2.05 ms |
| User embedding (two-tower forward pass) | 0.31 ms | 0.53 ms | 0.59 ms |
| **Total** | 21.31 ms | 25.35 ms | 60.97 ms |

Stage shares below are each stage's p50 against the total p50. They are
approximate and do not sum to 100%: the total is the median of per-request
sums, not the sum of per-stage medians.

## Retrieval dominates, and not because of Faiss

Candidate retrieval is the largest stage at roughly 41% of p50, ahead of
reranking at about 30%. The Faiss search is not what costs: the
`retrieval_ms` span covers either an index search *or* the cold-start
popularity path, and that path reindexes the whole 51,282-item catalog
over `popularity`, fills missing values and sorts it, on every request
from a user with no usable click history. That is a full catalog sort
against a single dense-array search, and many validation users have no
usable history.

Reranking remains expensive for the reason previously measured:
`build_diverse_slate`'s near-duplicate check
(`docs/experiments/reranking-diversity.md`) compares each candidate
against every already-selected item, an `O(n²)`-shaped cost the other
stages, all single dense-array operations, do not have. Retrieving more
candidates than needed (`RETRIEVAL_MULTIPLIER`,
`docs/operations/inference-path.md`) feeds that cost directly.

The p99 figures carry a caveat the p50s do not. Feature lookup's p99 of
21.97 ms against a p50 of 1.32 ms is a tail against a containerized
Redis over loopback, and the total p99 of 60.97 ms is dominated by a
small number of such requests. Treat the p50 and p95 columns as the
stable signal here.

## Superseded: the 2026-08-21 measurement

An earlier run of this same instrumentation reported a different result,
and it is kept here rather than removed because the reversal is the
point.

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Feature lookup (the online feature store) | 0.75 ms | 1.07 ms | 1.77 ms |
| User embedding (two-tower forward pass) | 0.30 ms | 0.46 ms | 0.68 ms |
| Candidate retrieval (Faiss) | 0.22 ms | 0.38 ms | 1.03 ms |
| Feature building (category/content-similarity) | 0.58 ms | 1.21 ms | 1.82 ms |
| Ranking (logistic regression) | 1.49 ms | 2.92 ms | 3.63 ms |
| Reranking (diversity + freshness) | 8.88 ms | 11.06 ms | 12.24 ms |
| **Total** | 12.79 ms | 14.96 ms | 17.09 ms |

That measurement concluded reranking was roughly 70% of request time and
that candidate retrieval, at 0.22 ms, was among the cheapest stages.
Both statements were true of the pipeline as it stood on 2026-08-21.
Neither is true now, and the pipeline is what changed:

- Retrieval depth was raised from 50 to 1,000 candidates on 2026-08-24
  (`docs/experiments/evaluation-integrity.md`), so every downstream
  stage scores twenty times as many candidates.
- The cold-start popularity path was added on 2026-08-24, after the
  zero-vector serving defect was diagnosed. It did not exist when the
  earlier table was measured, and it is the dominant retrieval cost now.

The earlier numbers were not wrong when taken. They describe a pipeline
that no longer exists, which is why the current table replaces them
rather than being averaged with them.

## Limitations

Measured on one developer machine against the containerized
demonstration stack, not production hardware. Absolute values depend on
local CPU, container limits and Redis locality, and are not portable.
The report records this alongside the numbers.
