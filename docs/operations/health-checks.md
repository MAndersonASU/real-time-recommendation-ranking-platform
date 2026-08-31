# Health and readiness

The API exposes two endpoints for different operational questions.
Both are implemented in `src/recommender/serving/app.py`.

## `GET /health`

This is the process liveness check:

```json
{"status": "ok"}
```

It does not query Redis or reload model artifacts. Docker uses this
endpoint to decide whether the running API process can answer HTTP
requests.

## `GET /ready`

This endpoint reports whether the serving context is available. If the
model, content, index, and ranking pipeline have not loaded, it returns
HTTP `503`.

A ready response has this shape:

```json
{
  "ready": true,
  "dependencies": {
    "model_index_ranking": "ok",
    "redis": "ok"
  },
  "durable_features": {
    "snapshot_id": "...",
    "built_at": "...",
    "data_as_of": "...",
    "data_age_seconds": 0,
    "users": 0,
    "is_stale": true,
    "refresh_policy": "..."
  }
}
```

The durable-feature values above show the response structure; actual
counts and times come from the loaded snapshot. The data are a frozen
historical set, so readiness reports their age instead of presenting a
service restart as a data refresh.

## Redis is a degraded dependency

Readiness sends a real `PING` to Redis. If it fails, the API remains
ready and reports:

```json
{
  "ready": true,
  "dependencies": {
    "model_index_ranking": "ok",
    "redis": "degraded (durable-features-only personalization)"
  }
}
```

Recent-click features are unavailable in this condition, but durable
history and the trained pipeline can still produce a personalized
response. Removing the instance from service would discard that useful
capacity.

## Container startup

The API service has no Compose `depends_on` entry for Redis or Kafka.
Required artifacts are loaded during application startup. Redis is
contacted later by readiness and recommendation requests.

This behavior has been verified with Redis absent: `/health` responded,
`/ready` reported degraded Redis, and `/recommend` still returned a
response using durable features.

See [configuration](configuration.md),
[serving fallback](serving-fallback.md), and
[restart and dependency testing](restart-and-failure-testing.md).
