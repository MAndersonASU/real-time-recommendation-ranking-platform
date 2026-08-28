# Low-Latency State Storage

Gives recent user features (`docs/operations/online-features.md`) a real, external,
low-latency home instead of only living inside one Python process's
memory. Implementation: `src/recommender/features/state_store.py`.

## Redis, not Feast

The recent-feature side of the online feature store needs one thing: a store that can be
written to and read from in well under a millisecond, with keys that
expire on their own. Feast is a full feature-store framework — it manages
feature definitions, materialization jobs, and point-in-time joins as its
own layer, typically sitting on top of a store like Redis anyway. That
machinery earns its cost once a project has many features, many models,
and multiple serving surfaces that all need a shared, versioned feature
definition layer. This project has two recent features (`docs/operations/online-features.md`) and one consumer of them, so Feast would add an entire
framework's worth of concepts to solve a coordination problem that
doesn't exist here. Redis plus two plain functions does the actual job.

## What's stored

`save_recent_features` writes a user's full `RecentUserFeatures` record as
a single JSON string under `recent_features:<user_id>`, with a 24-hour
expiry — a user who stops sending events should eventually fall out of
the store rather than being served forever from a stale snapshot.
`load_recent_features` returns `None` for a user with no key, whether
because they've never sent an event or their key expired; callers treat
that `None` as the cold-start case handled by `docs/experiments/cold-start.md`, not
an error.

## Verified against a real container

`verify_state_store.py` writes one real record to the actual Redis
container (`docker-compose.yml`), reads it back, and confirms every field
matches — not a mock. It also measures real read latency over 200 lookups
against the running container: **0.29 ms p50, 1.12 ms p99**. This is the
number behind the component's "low-latency feature path" exit criterion.

## Client timeout and retry policy

`build_client` sets a 0.2-second connect and socket timeout, and an
explicit, empty retry policy (`redis.retry.Retry(NoBackoff(), 0)`,
`retry_on_error=[]`) — not left to redis-py's own default. That default
retries a connection error once with a backoff delay, which was found
(not assumed) to silently double a failed lookup's cost against an
earlier, longer timeout. 0.2s is still ~180x this component's own
measured 1.12ms p99 above, generous headroom for jitter against a
healthy instance, while capping what an unhealthy one can cost a
request.

`RedisCircuitBreaker` (same module) sits in front of this: after
`failure_threshold` consecutive failures it stops attempting the
connection at all for `cooldown_seconds`, so a genuinely down Redis
doesn't make every concurrent request separately pay the timeout above.
One instance lives on `ServingContext`
(`recommender.serving.pipeline`), shared across every request the
process serves. See `docs/operations/serving-fallback.md` for what a
degraded Redis actually does to a response.
