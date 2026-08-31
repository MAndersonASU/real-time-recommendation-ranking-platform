# Replay evaluation

This evaluation calls the real `recommend()` path for historical replay
impressions and checks whether the returned top 10 contains the recorded
click.

Implementation:
`src/recommender/tracking/replay_evaluation.py`.

## What this simulation uses

The evaluation runs retrieval, ranking, and reranking, but it does not
reconstruct the exact online state that existed at each historical
moment.

| State source | What the run reads |
|---|---|
| Durable features | Current cache built from validation data |
| Recent features | Whatever is currently stored in Redis |
| Request labels | Historical impressions from `replay` |

This differs from a live A/B test, where the system has received real
traffic continuously. It also differs from the point-in-time
[serving-path evaluation](serving-path-end-to-end-evaluation.md).

## Result

A seeded uniform sample selected 500 impressions from the full replay
split. Every sampled impression contained a real click.

| Measure | Value |
|---|---:|
| Hit rate@10 | 0.0 |
| Distinct sampled users | 497 |
| Users absent from the durable validation cache | 465 (93.6%) |
| Users with a Redis record | 0 (0%) |
| Impressions using global-popularity retrieval | 468 |
| Impressions using durable-history retrieval | 32 |

The sample is uniform, not the first 500 on-disk rows. The zero result
therefore survives the correction of an older first-N sampling method.

## Why the result is zero

For 468 impressions, neither durable nor recent history was available.
Those requests correctly used the shared global-popularity candidate
pool.

The other 32 impressions used real durable history after
`SERVING-DURABLE-HISTORY-69`. None contained the clicked article in the
served top 10. A sample of 32 personalized requests is too small to
expect a visible hit reliably at the roughly 1% hit-rate scale measured
elsewhere.

The aggregate zero is therefore explained by this run's feature
coverage and small durable-only subgroup. It does not show that
durable-history retrieval has no effect: the dedicated
[durable-history evaluation](durable-history-fallback.md) measures its
slate diversity and catalog coverage on a much larger controlled cohort.

## What this result means

This run mostly measures cold-start behavior because its users do not
match the available online state. A replay is informative only when the
feature state matches the historical population being replayed.

A stronger replay would first stream the matching historical events into
an isolated Redis store, then evaluate requests against that controlled
state. The current run intentionally does not claim that level of
point-in-time reconstruction.

See [project limitations](../limitations.md) and the
[inference path](../operations/inference-path.md).
