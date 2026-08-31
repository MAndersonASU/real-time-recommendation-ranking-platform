# Redis recent-feature store

Redis stores recent user features outside the consumer process.

Implementation:
`src/recommender/features/state_store.py`.

## Stored record

`save_recent_features()` writes one JSON value under:

```text
recent_features:<user_id>
```

The value contains:

- recent clicked article IDs;
- impressions seen;
- clicks seen; and
- last event time.

The key expires after 24 hours. `load_recent_features()` returns `None`
when the key never existed or expired.

An absent recent key does not necessarily mean the user has no history.
Retrieval next checks bounded durable history, then uses global
popularity only when both sources are unusable.

## Why Redis is sufficient

The project has one recent-feature contract and one serving application.
It needs fast reads, writes, expiration, and atomic updates.

Feast would add feature registration, materialization jobs, and another
serving layer, often backed by Redis itself. That coordination is not
needed at the current scale.

## Timeouts and retry

`build_client()` configures:

| Setting | Value |
|---|---|
| Connect timeout | 0.2 seconds |
| Socket timeout | 0.2 seconds |
| Automatic retries | 0 |

A healthy Redis lookup measured 0.29 ms median and 1.12 ms p99, so the
timeout leaves substantial local jitter allowance while bounding an
outage.

The shared `RedisCircuitBreaker` opens after repeated transport
failures. It skips Redis during a cooldown and allows one half-open
probe afterward.

Parsing errors in a returned value are not counted as Redis transport
failures. They still propagate as data errors.

## Atomic event application

The streaming path uses a Lua operation to claim an event, load current
state, apply the event, and save the result atomically. This prevents
duplicate application and lost updates from concurrent consumers.

Processed-event claims have their own retention window, so idempotency
is bounded rather than permanent.

## Verification

`verify_state_store.py` writes a real record to the Compose Redis
container, reads it back, compares every field, and measures 200 reads.

Additional integration checks cover:

- concurrent atomic updates;
- duplicate delivery;
- circuit-breaker behavior; and
- append-only-file recovery after `SIGKILL`.

See [online features](online-features.md),
[streaming consumer](streaming-consumer.md),
[serving fallback](serving-fallback.md), and
[recovery testing](recovery-testing.md).
