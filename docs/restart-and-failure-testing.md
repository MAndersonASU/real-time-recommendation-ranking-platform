# Testing Restart and Failure Paths

Five real scenarios, tested against the actual running containers, not
simulated. Every result below came from actually stopping, restarting,
or breaking something in the live `docker compose` topology.

## A real coupling found and removed: the API never needed Kafka

`docker-compose.yml`'s `api` service had `depends_on: kafka: condition:
service_healthy`, blocking API startup until Kafka reported healthy —
even though the live API never consumes from or produces to Kafka at
request time; only the offline replay/consumer scripts from Phase 6 do.
Removed as a real, unnecessary coupling, found specifically by asking
what a Kafka interruption should and shouldn't affect.

## Five real results

| Scenario | What was done | Result |
|---|---|---|
| Kafka interruption | Stopped `recommender-kafka`, rebuilt and started the API fresh | API started immediately, served a normal request correctly — no effect at all, confirming the dependency removal above was correct |
| State-store (Redis) interruption | Stopped `recommender-redis` on the running API | `/ready` reported `degraded (falls back to popularity ranking)`; `/recommend` still returned a valid response via the popularity fallback |
| Graceful fallback | Same as above | `durable_features_used: false` in the response — honestly reporting no real personalization happened, not disguising the fallback as a normal result |
| Service restart | `docker restart recommender-api` | Came back healthy and serving correctly, with no manual intervention |
| Missing artifact | Renamed the real trained model file on disk, then restarted the container | Startup failed loudly with the exact diagnostic message from `docs/configuration.md` (`"a required model/index/ranking-pipeline file was not found..."`), not a silent or confusing crash |

## Recovery, verified both ways

Redis recovered on its own — restarting Redis alone was enough for the
already-running API's next request to report `redis: "ok"` again, no
API restart needed. The missing-artifact case needed the file restored
*and* a restart, which is the correct, expected behavior: a process
that failed to start because of a missing dependency has to be
restarted once that dependency is back, not expected to somehow
recover mid-failure.
