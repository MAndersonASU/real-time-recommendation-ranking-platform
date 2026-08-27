# Hardening Configuration

One typed settings object for every environment-dependent value the
serving app reads, a real slot for a secret this project doesn't have
yet, an explicit port, and a startup that fails loudly on a missing
model artifact instead of crashing unexplained on the first request.
Implementation: `src/recommender/serving/config.py`.

## Environment-based configuration

`Settings` (a `pydantic_settings.BaseSettings`) reads `REDIS_URL` and
`API_PORT` from the environment, or from a local, gitignored `.env`
file, with the exact defaults this project has always used —
`redis://localhost:6379/0`, port `8000`. Every field has a safe default,
so nothing about running this project locally, exactly as it always
has, requires setting anything. Only a containerized or otherwise
non-default deployment needs to actually configure something.

## Secret exclusion, for a secret this project doesn't have yet

There is no real credential anywhere in this project today — Redis and
Kafka both run without authentication locally. `redis_password` exists
as a typed `SecretStr | None` field anyway: `SecretStr` means the value
never appears in a `repr()`, a `str()`, or an accidental log line —
`str(settings)` prints `**********`, not the real password, even for
someone who never intended to log it. `redis_url_with_auth()` weaves it
into the connection string at the one point it's actually needed. This
is the pattern in place *before* a real secret exists, not retrofitted
after one leaks.

`redis_password` is carried all the way through `redis_url_with_auth()`
into a corresponding `requirepass` on the Redis service in
`docker-compose.yml`, so setting a real `REDIS_PASSWORD` actually takes
effect end to end -- verified directly (real `NOAUTH` on an
unauthenticated attempt, real success both via `redis-cli -a` and via
this project's own `redis_url_with_auth()`, and the same key still
present after a real container restart) -- see `docker-compose.yml`'s
own comments for detail.

## Explicit ports

`API_PORT` flows from the environment through `docker-compose.yml`
through the Dockerfile's shell-form `CMD` (`--port ${API_PORT:-8000}`)
to the running `uvicorn` process — one real, traceable path, not a port
number hardcoded in two or three different places that could silently
drift apart.

## Validated startup dependencies

`build_serving_context()` can raise a real `OSError` if a model, index,
or ranking-pipeline file is missing — e.g. the data volume wasn't
mounted, or the offline pipeline was never run. That's fatal: unlike a
single Redis call, which `safe_recommend` already falls back around,
there's no fallback for "the whole serving context couldn't even be
built." The app's lifespan now catches exactly that case, logs a
specific, actionable message naming the likely cause, and re-raises —
failing immediately and loudly at startup instead of the first request
hitting an unexplained crash.
