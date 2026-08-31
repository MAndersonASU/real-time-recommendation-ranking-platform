# Test service restarts and dependency failures

These checks exercise the running Docker Compose services. They cover
failure behavior beyond the Kafka consumer checks in
[recovery testing](recovery-testing.md).

## Dependency boundaries

The API does not depend on Kafka at request time. Kafka is used by the
replay and consumer utilities, so an unavailable broker must not block
API startup or recommendation requests.

The API also does not wait for Redis before starting. It creates the
Redis client at startup but connects only when a request or readiness
check uses it. Redis is optional for recent features; the model
artifacts are required.

## Verified scenarios

| Scenario | Action | Observed result |
|---|---|---|
| Kafka unavailable | Stop Kafka and start the API | API starts and serves recommendations |
| Redis unavailable | Stop Redis while the API is running | `/ready` reports degraded Redis; requests continue |
| API restart | Restart the API container | Health check recovers and recommendations work |
| Missing model artifact | Hide a required model file and restart the API | Startup exits with an actionable error |
| Redis recovery | Restart Redis without restarting the API | A successful probe restores normal Redis status |

## Redis degradation

When Redis is unavailable, the response can still use durable user
history already loaded in memory. A verified request reported:

- `durable_features_used: true`;
- `recent_features_used: false`; and
- `is_fallback: false`.

This is reduced personalization, not necessarily a popularity fallback.
The shared circuit breaker opens after repeated Redis failures, allowing
later requests to skip a known-bad connection. After its cooldown, one
probe checks whether Redis has recovered.

Timing during the container test depended on Docker networking. The
first failed connections took longer; a request after the breaker
opened returned in 0.29 seconds. That value describes the local check,
not a service target.

## Required artifacts

The API cannot serve without its model, content, index, and ranking
artifacts. If one is missing, startup logs that a required file could
not be found and asks the operator to check the data mount and offline
pipeline.

Restoring the file is not enough for a process that already exited. The
API container must be started again after the artifact is available.

See [configuration](configuration.md),
[health checks](health-checks.md), and
[serving fallback](serving-fallback.md).
