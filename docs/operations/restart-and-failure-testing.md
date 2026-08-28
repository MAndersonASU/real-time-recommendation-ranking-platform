# Testing Restart and Failure Paths

Five real scenarios, tested against the actual running containers, not
simulated. Every result below came from actually stopping, restarting,
or breaking something in the live `docker compose` topology.

## A real coupling found and removed: the API never needed Kafka

`docker-compose.yml`'s `api` service had `depends_on: kafka: condition:
service_healthy`, blocking API startup until Kafka reported healthy —
even though the live API never consumes from or produces to Kafka at
request time; only the offline replay/consumer scripts from the streaming pipeline do.
Removed as a real, unnecessary coupling, found specifically by asking
what a Kafka interruption should and shouldn't affect.

## Five results

| Scenario | What was done | Result |
|---|---|---|
| Kafka interruption | Stopped `recommender-kafka`, rebuilt and started the API fresh | API started immediately, served a normal request correctly — no effect at all, confirming the dependency removal above was correct |
| State-store (Redis) interruption | Stopped `recommender-redis` on the running API | `/ready` reported `degraded (durable-features-only personalization)`; `/recommend` still returned a real, personalized response, not the popularity fallback (REDIS-DEGRADED-PATH-61 -- re-verified against these same live containers after that fix) |
| Graceful degradation | Same as above | `durable_features_used: true`, `recent_features_used: false`, `is_fallback: false` in the response -- the trained ranking model and this user's real durable features still ran; only the recent-clicks input from Redis was empty. The first two requests after Redis stopped each took several seconds (a real cost of Docker's stopped-container networking in this environment, not an indefinite hang); the third, after the shared circuit breaker's 3-failure threshold tripped, returned in 0.29s -- it skipped attempting the connection entirely |
| Service restart | `docker restart recommender-api` | Came back healthy and serving correctly, with no manual intervention |
| Missing artifact | Renamed the real trained model file on disk, then restarted the container | Startup failed loudly with the exact diagnostic message from `docs/operations/configuration.md` (`"a required model/index/ranking-pipeline file was not found..."`), not a silent or confusing crash |

## Recovery, verified both ways

Redis recovered on its own — restarting Redis alone was enough for the
already-running API's next request to report `redis: "ok"` again (and
the circuit breaker to close again on that success), no API restart
needed. The missing-artifact case needed the file restored
*and* a restart, which is the correct, expected behavior: a process
that failed to start because of a missing dependency has to be
restarted once that dependency is back, not expected to somehow
recover mid-failure.
