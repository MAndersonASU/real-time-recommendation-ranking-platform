# Failure-Safe Fallbacks

Returns a safe, popularity-ranked response when a real dependency the
main inference path needs — Redis, the model, the index — turns out to
be unavailable, instead of the request failing outright. Implementation:
`src/recommender/serving/fallback.py`.

## A different question than Phase 7's cold start

Phase 7's cold-start handling (`docs/cold-start.md`) answers "we don't
know anything about this particular user" — a data problem the real
path already handles gracefully, without falling back to anything
simpler. This step answers a different question: "the real path itself
cannot run right now," because a dependency it needs is down or broken.
`safe_recommend` wraps `recommend` and only falls back when that second,
infrastructural kind of failure actually happens.

## Deliberately narrow exception handling

`DEPENDENCY_FAILURE_EXCEPTIONS` is `(redis.exceptions.RedisError,
RuntimeError, OSError)` — not a bare `except Exception`. The same
discipline already applied to malformed streaming messages
(`docs/streaming-consumer.md`): catching everything would risk quietly
hiding a real logic bug behind a "safe" fallback response that looks
fine on the surface. `RedisError` covers the feature store being
unreachable; `RuntimeError` is the common base both PyTorch and Faiss
raise for an unusable model or index; `OSError` covers a missing or
unreadable model file on disk.

## The fallback itself: Phase 2's first baseline, one more time

`build_fallback_response` ranks the whole catalog by plain training-set
popularity — the exact same `rank_by_popularity` function built in Step
2.2, the very first thing this project ever evaluated. No model, index,
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
