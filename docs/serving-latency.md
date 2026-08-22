# Latency By Stage

Measures where a real request's time actually goes, stage by stage, not
just the one end-to-end number the inference path already produced
(`docs/inference-path.md`). Implementation:
`recommend()`'s optional `stage_timings` parameter in
`src/recommender/serving/pipeline.py`; measurement script
`src/recommender/serving/verify_latency.py`.

## One code path, opt-in instrumentation

`recommend()` takes an optional `stage_timings` dict. When one is passed,
every stage records its own elapsed time into it; when it's left `None`
(the default, and what every earlier step's tests and verification
already call), a request pays only the cost of a few no-op
`perf_counter()` checks. This measures the actual production code path
directly, rather than a second, separately maintained timing harness
that could quietly drift out of sync with what really executes.

## Real measurement, 100 real validation users, six stages

| Stage | p50 | p95 | p99 |
|---|---|---|---|
| Feature lookup (Phase 7) | 0.75 ms | 1.07 ms | 1.77 ms |
| User embedding (two-tower forward pass) | 0.30 ms | 0.46 ms | 0.68 ms |
| Candidate retrieval (Faiss) | 0.22 ms | 0.38 ms | 1.03 ms |
| Feature building (category/content-similarity) | 0.58 ms | 1.21 ms | 1.82 ms |
| Ranking (logistic regression) | 1.49 ms | 2.92 ms | 3.63 ms |
| Reranking (diversity + freshness) | **8.88 ms** | **11.06 ms** | **12.24 ms** |
| **Total** | 12.79 ms | 14.96 ms | 17.09 ms |

## The real, non-obvious finding

Reranking — not the model forward pass, not Faiss, not the ranking
model — is roughly **70% of total request time**. That was not the
expected bottleneck going in; the two-tower embedding and Faiss search
are the parts that sound expensive (a neural network, a similarity
search over the whole catalog) and turned out to be the cheapest stages
measured, each under half a millisecond at p50. The real cost is
`build_diverse_slate`'s near-duplicate check (`docs/reranking-
diversity.md`): a pairwise TF-IDF similarity comparison against every
already-selected item for every candidate under consideration, an
`O(n²)`-shaped cost that the other stages, all single dense-array
operations, simply don't have. Retrieving more candidates than needed
(`RETRIEVAL_MULTIPLIER`, `docs/inference-path.md`) directly feeds this
cost — more candidates handed to reranking means more pairwise
comparisons, a concrete, measured tradeoff between retrieval headroom
and reranking latency that wasn't visible from the single end-to-end
number `docs/inference-path.md` reported alone.
