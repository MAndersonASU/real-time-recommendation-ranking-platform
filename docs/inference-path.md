# Inference Path

Wires everything built since Phase 1 into one real, callable path: online
features → user embedding → candidate retrieval → ranking → reranking →
a Top-K response validated against the serving contract (`docs/serving-
contract.md`). Implementation: `src/recommender/serving/pipeline.py`.

## Load once, not per request

`ServingContext` holds every artifact `recommend()` needs — the trained
two-tower model, a fresh exact Faiss index built from its current catalog
embeddings, the trained ranking model, durable per-user features, and a
Redis client — all loaded once by `build_serving_context()`. A real
request only ever does a dictionary lookup or a forward pass through an
already-trained model; nothing about serving a single user re-trains or
re-fits anything.

## The one place this project's retrieval quality actually gets used live

Every offline evaluation since Phase 2 ranked the same frozen candidate
set — MIND's own impression list — because Step 3.5 found the retrieval
model's own top-N badly weakened by a 284-distinct-vector limitation in
the item tower. A live request has no impression list to fall back on:
it has to generate its own candidates from the whole catalog through the
Faiss index, exactly what `recommend()` does with `faiss_index.search`.
This is genuinely the first place in the whole project where retrieval's
own top-N output becomes the actual candidate source, not a stand-in
for one — and it inherits the same diagnosed limitation as a result.
Ranking on top of those candidates still recovers reasonable quality
(Step 4.5 showed ranked scoring works even over a retrieval-narrowed
candidate pool), but the pool itself starts from retrieval's real,
already-documented ceiling, not a clean slate.

## A disclosed asymmetry between the live path and offline training

The two-tower embedding and the content-similarity profile here only
ever see a user's last 20 recent clicks, since that is the cap Phase 7's
low-latency store chose (`docs/state-store.md`). Offline training's own
content profile (`ranking/features.py`) pools a user's entire history
string, uncapped. This is a real, disclosed consequence of Phase 7's own
latency/storage tradeoff, not an oversight — `user_history_length` uses
the durable `lifetime_click_count` specifically because that field, and
only that field, still carries the same uncapped meaning training used.

## Verified against real infrastructure

`verify_inference_path.py` builds the real serving context and calls
`recommend()` for 20 real users from the validation split plus one user
that has never existed anywhere. Every response validated against the
typed contract, returned exactly the requested count, and the unknown
user correctly came back with both feature flags false. Measured,
single-request, single-threaded latency: **12.3ms p50, 15.5ms p99** —
this phase's own rigorous per-stage latency breakdown is Step 8.5's job,
not this step's.
