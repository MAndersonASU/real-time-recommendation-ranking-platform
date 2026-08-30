# Inference Path

Wires everything built since data ingestion into one real, callable path: online
features → user embedding → candidate retrieval → ranking → reranking →
a Top-K response validated against the serving contract (`docs/operations/serving-contract.md`). Implementation: `src/recommender/serving/pipeline.py`.

## Load once, not per request

`ServingContext` holds every artifact `recommend()` needs — the trained
two-tower model, a fresh exact Faiss index built from its current catalog
embeddings, the trained ranking model, durable per-user features, and a
Redis client — all loaded once by `build_serving_context()`. A real
request only ever does a dictionary lookup or a forward pass through an
already-trained model; nothing about serving a single user re-trains or
re-fits anything.

## Which history retrieval actually uses

`select_retrieval_history` (SERVING-DURABLE-HISTORY-69,
`docs/engineering-review-register.md`) chooses exactly one history for
the two-tower embedding, Faiss retrieval, and content-similarity
profile, in this order, never merging two of them:

1. **Recent** — Redis's own recent-clicked-items list, when it contains
   at least one id this catalog's item vocabulary recognises. A record
   that exists but carries only impressions (no real clicks, or clicks
   this vocab doesn't know) is not usable and falls through to durable,
   exactly like no record at all.
2. **Durable** — the user's bounded offline history
   (`DurableUserFeatures.history_item_ids`), when Redis has nothing
   usable. This is what a returning user with a real click history but
   a healthy, merely empty Redis record now retrieves on, instead of
   the identical global-popularity pool every such user used to
   receive regardless of who they were.
3. **Global popularity** — an explicit empty history, when neither
   exists. `has_retrieval_signal` below detects the resulting
   zero-norm embedding and routes to a real popularity ranking rather
   than an arbitrary Faiss tie order.

The response's `retrieval_history_source` field names which of the
three a given request actually used -- distinct from the older
`durable_features_used`/`recent_features_used` flags, which report
only whether *some* feature lookup found a record, not what retrieval
itself keyed on.

## The one place this project's retrieval quality actually gets used live

Every offline evaluation since the baselines ranked the same frozen
candidate set — MIND's own impression list, not a pool retrieval itself
produced (`docs/experiments/ranking-features.md`). A live request has no
impression list to fall back on: it has to generate its own candidates
from the whole catalog through the Faiss index, exactly what
`recommend()` does with `faiss_index.search`. This is genuinely the
first place in the whole project where retrieval's own top-N output
becomes the actual candidate source, not a stand-in for one.

Retrieval quality over the full catalog remains weak in an absolute
sense (`docs/experiments/retrieval-evaluation.md`): the item-tower fix
raised distinct embeddings from 284 to 50,704 across the 51,282-item
catalog and every retrieval metric with it, but did not produce a
working full-catalog retriever. Ranking evaluation
(`docs/experiments/ranking-evaluation.md`) does not measure ranking
quality over this live, retrieval-narrowed pool — it deliberately uses
MIND's own frozen impression list instead, to isolate retrieval quality
from ranking quality. The pool a live request actually ranks over is
measured separately, end to end
(`docs/experiments/serving-path-end-to-end-evaluation.md`), and starts
from retrieval's real, already-documented ceiling, not a clean slate.

## A disclosed asymmetry between the live path and offline training

The two-tower embedding and the content-similarity profile here only
ever see a user's last 20 recent clicks, since that is the cap the online feature store's
low-latency store chose (`docs/operations/state-store.md`) -- now also
the cap `DurableUserFeatures.history_item_ids` uses, so a durable-history
fallback sees the same bound a real recent history would have. Offline training's own
content profile (`ranking/features.py`) pools a user's entire history
string, uncapped. This is a real, disclosed consequence of the online feature store's own
latency/storage tradeoff, not an oversight — `user_history_length` uses
the durable `lifetime_click_count` specifically because that field, and
only that field, still carries the same uncapped meaning training used.

## Verified against real infrastructure

`verify_inference_path.py` builds the real serving context and calls
`recommend()` for 20 real users from the validation split plus one user
that has never existed anywhere. Every response validated against the
typed contract, returned exactly the requested count, and the unknown
user correctly came back with both feature flags false. Measured, single-request, single-threaded latency: 12.3ms p50, 15.5ms
p99. That measurement predates the retrieval-depth and cold-start
changes recorded in `docs/experiments/serving-latency.md` and is
superseded by the 21.31ms p50 / 60.97ms p99 measured there under the
current pipeline; this component's own rigorous per-stage latency
breakdown belongs to that document, not this one.
