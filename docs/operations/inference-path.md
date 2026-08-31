# Recommendation inference path

`recommend()` connects online features, user embedding, retrieval,
ranking, reranking, and the typed response.

Implementation:
`src/recommender/serving/pipeline.py`.

## Request flow

| Operation | Output |
|---|---|
| Feature lookup | Durable and recent user features plus fallback flags |
| History selection | Recent, durable, or no history |
| User embedding | Two-tower query vector |
| Candidate retrieval | Up to 1,000 articles from Faiss or global popularity |
| Feature building | Ranker inputs for each candidate |
| Ranking | Calibrated click probabilities |
| Reranking | Diversity and optional historical freshness policy |
| Response | Top-K items and retrieval-source metadata |

`safe_recommend()` wraps only known dependency failures with the
documented fallback. Unexpected programming or ranking errors remain
errors.

## Loaded once at startup

`ServingContext` contains:

- the two-tower model;
- an exact Faiss index built in memory from current catalog embeddings;
- the ranking pipeline;
- article metadata and feature context;
- durable user features; and
- a Redis client and circuit breaker.

`build_serving_context()` creates these objects once. A request performs
lookups and inference; it does not fit or train anything.

## Retrieval history order

`select_retrieval_history` chooses one source and never merges histories:

1. **Recent:** Redis clicks that exist in the current item vocabulary.
2. **Durable:** bounded offline history when recent clicks are absent or
   unusable.
3. **Global popularity:** no usable history from either source.

A Redis record containing impressions but no usable clicks falls through
to durable history.

`retrieval_history_source` reports the chosen source. This is different
from `durable_features_used` and `recent_features_used`, which only say
whether those feature records were found.

## Full-catalog retrieval

A live request does not receive MIND's supplied candidate list. Faiss
must find candidates from 51,282 catalog articles before ranking can
help.

That is why the high candidate-list ranking values do not represent live
quality. The
[end-to-end evaluation](../experiments/serving-path-end-to-end-evaluation.md)
measures the assembled path and reports hit rate@10 of 0.0084.

The [retrieval evaluation](../experiments/retrieval-evaluation.md)
measures N=100 full-catalog retrieval separately.

## Offline and online history difference

Recent and durable retrieval histories are capped at 20 items. Offline
ranking-feature construction can pool the full recorded history.

`user_history_length` uses durable `lifetime_click_count` so that input
keeps the uncapped meaning used during training. The content profile and
user embedding use the bounded serving history.

This is a documented latency and storage tradeoff.

## Verification

`verify_inference_path.py` builds the real context and requests
recommendations for 20 validation users plus one unknown user. It checks:

- response schema;
- requested item count; and
- false durable and recent flags for the unknown user.

Its older 12.3 ms median and 15.5 ms p99 values predate retrieval-depth
and fallback changes. The current profile is
21.78 ms median and 52.79 ms p99 in
[serving latency](../experiments/serving-latency.md).

See [serving contract](serving-contract.md),
[online features](online-features.md), and
[serving fallback](serving-fallback.md).
