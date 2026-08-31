# Limitations

This page explains what the published results cannot establish. It
focuses on data, evaluation, and serving behavior. Implementation
findings and accepted engineering constraints are recorded separately
in the [engineering review register](engineering-review-register.md).

## Summary

The main limits are:

- most users have little recorded history;
- the local feature stores often begin with no recent state;
- offline and online feature inputs are not identical;
- MIND clicks reflect another recommender's exposure choices;
- no counterfactual or live A/B outcome is available;
- new articles require a content refit;
- no untouched final test split remains;
- retrieval quality is low in absolute terms.

## Most users have sparse histories

Within one data window, the median user has only one or two
interactions. A small set of active users raises the mean, with observed
maximums between 18 and 62 interactions.

This means the typical user offers little personalization signal. The
split between durable and recent features, and the cold-start fallback,
handle a common condition rather than a rare edge case.

## Cold start dominates an unseeded local system

The replay evaluation sampled 497 users:

- 93.6% did not appear in the validation split used to build the
  durable cache;
- 0% had a live Redis record at measurement time.

A local service that has not received continuous traffic therefore
starts close to a cold-start system. This result describes the measured
feature stores, not every possible deployment.

Evidence: [replay evaluation](experiments/replay-evaluation.md).

## Offline and online inputs differ

### History length

Offline content similarity can use a user's full recorded history. The
live path uses at most the 20 recent clicks stored in Redis. For the
separate `user_history_length` feature, serving uses the durable
`lifetime_click_count` so that the value is not silently capped at 20.

### Durable-feature age

Durable features are a frozen snapshot of the 2019 dataset. They are not
automatically refreshed. Restarting the API reloads the same snapshot.

The 24-hour setting is a warning threshold, not a refresh schedule.
`/ready` reports the real snapshot age and whether it exceeds that
threshold.

Evidence:
[inference path](operations/inference-path.md),
[serving cache](operations/serving-cache.md), and
[replay evaluation](experiments/replay-evaluation.md).

## Logged clicks contain selection bias

MIND impression logs were produced by Microsoft's existing news system.
A user could click only an article that system chose to show.

The project's hit rate, recall, NDCG, and MRR therefore measure
agreement with choices visible in those logs. They do not measure
unconditional user relevance. An article that this project would have
recommended, but the original system never displayed, cannot appear as
a successful outcome in the data.

## Counterfactual outcomes are unavailable

The logs do not show what a user would have clicked if they had seen a
different list. Offline evaluation can compare model orderings against
the observed click, but it cannot establish how users respond to new
recommendations.

A live controlled experiment would be required for that claim. The
frozen [research scenario](research-scenario.md) excludes a live A/B
test, and the [replay evaluation](experiments/replay-evaluation.md) is
not presented as one.

## No untouched final test split remains

Validation and replay results informed development decisions. They are
post-selection development evidence, not final estimates from data that
was held aside until all choices were complete.

The tuning fold reduces leakage for specific parameter decisions, but
it does not create a new untouched final split.

Evidence:
[evaluation protocol](experiments/evaluation-protocol.md) and
[evaluation integrity](experiments/evaluation-integrity.md).

## New articles require a refit

The content artifact contains vectors for the fitted catalog. The
TF-IDF vocabulary and SVD basis used to create those vectors are not
persisted as an online transformer.

A new article therefore cannot be projected into the existing
coordinate system during serving. Adding it to content-aware retrieval
requires refitting the transformation and retraining the item tower.

This matches the project's frozen-snapshot scope, but it is an important
limit of the phrase “content-aware retrieval.” The review register
tracks it as `ARTIFACT-TRANSFORMERS-07`.

## Retrieval remains weak

Adding title and abstract vectors corrected a known representation
problem and improved retrieval metrics. Even after that change, the
end-to-end serving evaluation found the clicked item in the
1,000-candidate pool only 14.14% of the time. Final hit rate@10 was
0.84%.

Ranking cannot recover an item that retrieval never returns. These
results are a limit on claims about the complete system, not a general
claim that learned retrieval cannot work.

Evidence:
[retrieval evaluation](experiments/retrieval-evaluation.md) and
[end-to-end evaluation](experiments/serving-path-end-to-end-evaluation.md).

## Durable retrieval history: resolved behavior

The live service once built the retrieval query only from recent Redis
clicks. A returning user with durable history but no recent Redis record
was treated like a cold-start user.

`select_retrieval_history` now chooses:

1. usable recent history;
2. otherwise, bounded durable history;
3. otherwise, global popularity.

Recent and durable histories are not merged. The response field
`retrieval_history_source` reports which source was used.

The dedicated
[durable-history evaluation](experiments/durable-history-fallback.md)
measures the corrected path for 7,790 eligible impressions against an
empty isolated Redis store. It reports post-change quality and slate
diversity. It is not a paired before-and-after experiment at that scale;
the earlier behavior is established by code and direct reproduction.

The register tracks this resolved finding as
`SERVING-DURABLE-HISTORY-69`.

## Bottom line

The project supports claims about offline behavior under documented
MIND protocols. It does not support claims about live user impact,
production scale, automatic catalog updates, or performance on a final
untouched population.
