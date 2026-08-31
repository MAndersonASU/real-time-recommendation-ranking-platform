# Configuration

The serving application reads environment-dependent values through one
typed `Settings` object in
`src/recommender/serving/config.py`.

## Application settings

| Variable | Default | Use |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `REDIS_PASSWORD` | unset | Optional Redis password |
| `API_PORT` | `8000` | Uvicorn and container port |

Values can come from environment variables or a local `.env` file.
`.env` is ignored by Git. The defaults support local use without extra
configuration.

Docker Compose also reads `API_BIND_HOST`. It defaults to
`127.0.0.1` so the API is local-only. Set it deliberately to expose the
port on another interface.

## Redis password

`redis_password` uses Pydantic `SecretStr`. Printing the settings object
shows masked text instead of the password.

`redis_url_with_auth()`:

- percent-encodes the password;
- inserts it into the connection URL only when needed; and
- leaves the default password-free URL unchanged.

Docker Compose passes the same `REDIS_PASSWORD` to Redis
`--requirepass` and to the API. A live check confirmed that an
unauthenticated command receives `NOAUTH`, authenticated clients work,
and saved data remains after a Redis restart.

## Port flow

`API_PORT` follows one path:

```text
environment → docker-compose.yml → container environment → uvicorn
```

The Docker command runs a shell only for variable expansion, then uses
`exec` so Uvicorn becomes the container's main process.

## Startup failures

`build_serving_context()` requires the model and ranking artifacts.
Missing files usually mean the data volume is absent or the offline
pipeline has not run.

The application catches that startup `OSError`, logs an actionable
message, and exits immediately. Redis is different: the API can start
without it and handle connection loss through the documented degraded
path.

See [serving fallback](serving-fallback.md) and
[containerization](containerization.md).
