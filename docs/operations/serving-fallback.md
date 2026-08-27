# Failure-Safe Fallbacks

Returns a safe, popularity-ranked response when a real dependency the
main inference path needs — Redis, the model, the index — turns out to
be unavailable, instead of the request failing outright. Implementation:
`src/recommender/serving/fallback.py`.

## A different question than the online feature store's cold start

the online feature store's cold-start handling (`docs/experiments/cold-start.md`) answers "we don't
know anything about this particular user" — a data problem the real
path already handles gracefully, without falling back to anything
simpler. This check answers a different question: "the real path itself
cannot run right now," because a dependency it needs is down or broken.
`safe_recommend` wraps `recommend` and only falls back when that second,
infrastructural kind of failure actually happens.

## Deliberately narrow exception handling

`safe_recommend` catches exactly one exception type:
`DependencyUnavailableError` (`recommender.serving.errors`). That type
is raised only at the three real per-request dependency boundaries --
the Redis lookup, the two-tower forward pass, and the Faiss search --
where the underlying library's own exception is caught and translated,
carrying the reason with it.

An earlier version caught `(redis.exceptions.RedisError, RuntimeError,
OSError)` directly. That was too broad to be safe: `RuntimeError` and
`OSError` are raised by plenty of code that is not a failing
dependency, so a genuine logic bug anywhere in feature construction,
ranking or reranking could surface as a "successful" popularity
response that looked fine from the outside.

Translating at the boundary keeps the catch narrow without losing
coverage: an unreachable feature store, an unusable model and an
unreadable index still degrade gracefully, while a programming error
propagates to the API's own error handling and is visible.

## The fallback itself: the popularity baseline, one more time

`build_fallback_response` ranks the whole catalog by plain training-set
popularity — the exact same `rank_by_popularity` function built for the popularity
baseline, the very first thing this project ever evaluated. No model, index,
ranking pipeline, or Redis lookup is needed to produce it. `score` here
is popularity normalized into `[0, 1]`, not a calibrated click
probability the way it is on the real path — a real, disclosed
difference in what the number means, honestly named rather than
pretended away. Both `durable_features_used` and `recent_features_used`
are always `False` on this path, since no feature lookup happens here
at all.

## Verified against a real, unmocked failure

`verify_fallback.py` builds the real serving context — the real
catalog, the real trained model, the real ranking pipeline — then
points its Redis client at a port nothing is listening on: a genuine
connection failure, not a simulated one. `safe_recommend` still returned
a full 10-item, contract-valid response, correctly reporting no real
personalization on either flag.

## Cold-start retrieval: popularity, not a zero-vector search

Distinct from the dependency fallback above, and handled inside
`recommend()` rather than by `safe_recommend`: a user with no usable
click history is not a failure, it is a normal request this system has
to answer well.

`TwoTowerModel.user_vector` averages the item vectors of whatever is in
the user's history, so an empty (fully masked) history produces an
exactly zero-norm user vector. Querying an inner-product Faiss index
with a zero vector scores every catalog item at exactly 0.0, so the
index returns an arbitrary tie order — the identical slate for every
history-less user — and the ranking model then receives a constant
`retrieval_score` and assigns every candidate the same probability.
This was directly observable on the live service: a `/recommend` call
for an unknown user returned three items with byte-identical scores,
all from one category.

Retrieval now checks whether the user vector carries any signal at all
and, when it does not, draws candidates from training-set popularity
instead, scaled into `[0, 1]` so `retrieval_score` keeps a meaning
comparable to an inner-product score. Popularity is reindexed over the
whole catalog rather than only the items that appear in the training
split, since an item with no training clicks has a real popularity of
zero rather than a missing value — without that, a catalog larger than
the training split's item set would yield fewer candidates than
requested.

This is a genuine improvement in cold-start behaviour, not a fix for
the retrieval-quality limitation described in
`docs/experiments/serving-path-end-to-end-evaluation.md`: it replaces an arbitrary
slate with a defensible one. Regression tests in `tests/test_pipeline.py`
assert that a history-less user never reaches the index and that a user
with real history still does.
