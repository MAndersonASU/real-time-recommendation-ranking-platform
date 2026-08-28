# Health and Readiness Checks

Two separate endpoints answering two genuinely different questions: is
this process alive, and can it actually serve a request right now.
Implementation: `src/recommender/serving/app.py`.

## Liveness (`GET /health`)

Always reports `{"status": "ok"}` once the process is running, with no
check of any dependency. This is deliberate: a liveness probe exists to
answer "has this process hung or crashed, should it be restarted" — not
"is it fully functional." A process still finishing its startup, or one
whose model failed to load, is still alive and shouldn't be killed and
restarted in a loop over a condition a restart can't fix.

## Readiness (`GET /ready`)

Answers a different question: can this instance actually serve traffic
right now. Two dependencies are checked, and treated very differently:

- **Model, index, and ranking pipeline** — whether `ServingContext`
  actually finished loading. This is fatal if missing: there is no
  per-request fallback for "the whole context never built" the way
  there is for a single failed Redis call. A caller hitting `/ready`
  before startup finishes gets a real `503`, not a response built
  against a context that doesn't exist.
- **Redis** — checked with a real `ping()`, but reported as a
  *dependency status*, not a readiness gate. An unreachable Redis only
  empties one input to an already-running pipeline — the recent-clicks
  record — while durable features, the trained model, and the ranking
  pipeline keep serving real, personalized responses
  (`docs/operations/serving-fallback.md`), without the service becoming
  unable to serve a valid response at all. Failing readiness
  outright over a degraded-but-working Redis would pull a perfectly
  serviceable instance out of a load balancer's rotation for the wrong
  reason.

```json
{
  "ready": true,
  "dependencies": {
    "model_index_ranking": "ok",
    "redis": "ok"
  }
}
```

A degraded Redis reports the same `ready: true`, with
`"redis": "degraded (durable-features-only personalization)"` instead —
verified with a real, unmocked connection failure the same way
`docs/operations/serving-fallback.md` verified the degraded path itself.

## This holds at container startup too, not just mid-request

`docker-compose.yml`'s `api` service has no `depends_on` entry for Redis
(DEPLOYMENT-CONTRACT-62): `build_serving_context` never connects to
Redis during startup, only constructs a client object, lazily connected
on its first real command, so there was never a real dependency here to
gate on. Verified against the live containers with Redis never started
at all, not merely stopped: `docker compose up -d api` alone (`redis`
never created) still reached a healthy `/health`, `/ready` still
reported `ready: true` with the same degraded Redis status shown
above, and `/recommend` returned a real, personalized response. An
earlier version of this compose file did block API
startup on Redis's health check — a real gap between what
`docs/architecture.md` claimed ("Redis is optional, startup does not
gate on it") and what the file actually did, found by this
verification.
