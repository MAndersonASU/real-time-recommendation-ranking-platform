# Serving fallback behavior

The service distinguishes normal cold start, Redis degradation, and a
required model or index failure. They do not all receive the same
response.

| Condition | Behavior |
|---|---|
| User has no history | Retrieve by global popularity, then use normal ranking and reranking |
| Redis is unavailable | Continue with durable features and durable history when available |
| Two-tower model or Faiss fails during a request | Return a simple popularity-ranked fallback response |
| Ranking or application code fails unexpectedly | Return an error; do not hide it as a fallback |

## Required-dependency fallback

`safe_recommend()` catches only
`DependencyUnavailableError`. The two-tower forward pass and Faiss
search translate their library errors into this type.

The narrow exception prevents a ranking, feature, or reranking bug from
appearing as a successful popularity response. Unexpected
`RuntimeError` or `OSError` values are not caught broadly.

`build_fallback_response()`:

- ranks the catalog with the training popularity baseline;
- requires no model, index, ranker, or Redis;
- returns both feature-used flags as `False`; and
- sets retrieval source to `global_popularity`.

Fallback `score` is popularity normalized to `[0, 1]`. It is not the
calibrated click probability returned by the normal ranking path.

Implementation:
`src/recommender/serving/fallback.py`.

## Redis degradation

Redis provides only recent clicks. The model, exact index, ranking
pipeline, and durable features are already in process memory.

`get_online_features()` catches Redis connectivity errors and returns an
absent recent record with `redis_unavailable=True`. Recommendation then
uses durable history if available and continues through the normal
personalized path.

`on_redis_degraded` emits the operational signal even though the
response is not a full fallback.

A shared `RedisCircuitBreaker` stops repeated connection attempts after
enough consecutive transport failures. After its cooldown, exactly one
request probes Redis.

## Cold start

An empty history produces a zero-norm user vector. Inner-product search
would score every article at zero and return an arbitrary tied order.

The pipeline detects that condition before Faiss and selects candidates
by catalog-wide training popularity. Articles absent from training
receive popularity zero, so the response can still contain the requested
number of candidates.

This is a normal historyless request, not a dependency failure. Ranking
and reranking still run.

## History source

For a healthy request, retrieval chooses:

1. usable recent clicks;
2. bounded durable history; or
3. global popularity.

A returning user with durable history does not fall to global popularity
merely because Redis is empty.

## Verification

`verify_fallback.py` creates the real serving context, then points Redis
to a closed port. A real user with durable features receives:

| Field | Result |
|---|---|
| `is_fallback` | `false` |
| `durable_features_used` | `true` |
| `recent_features_used` | `false` |
| Returned items | 10 |

This confirms Redis loss takes the degraded normal path.

Regression tests also verify:

- a historyless user does not query Faiss;
- a user with usable history does query Faiss;
- known model and index failures use the simple fallback; and
- unexpected code failures propagate.

See [cold-start behavior](../experiments/cold-start.md),
[state store](state-store.md), and
[inference path](inference-path.md).
