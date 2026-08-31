# Containerized services

Docker Compose runs:

- Kafka;
- Redis; and
- the FastAPI recommendation service.

Implementation: `Dockerfile`, `docker-compose.yml`, and
`src/recommender/serving/app.py`.

## API process

`app.py` exposes `POST /recommend` using the same
`RecommendationRequest` and `RecommendationResponse` models as the
Python serving code.

The FastAPI lifespan creates `ServingContext` once at startup through
`build_serving_context()`. The HTTP application does not maintain a
separate artifact-loading path.

## Data stays out of the image, on purpose

Models, ranking artifacts, processed content, and split data remain
under the local `data/` directory. They are not copied into the image.
Compose mounts `data/` read-only.

The Faiss index is rebuilt in memory from the validated content and
model artifacts at startup; it is not loaded as a persisted index file.

Keeping research artifacts outside the image avoids redistributing MIND
and allows artifacts to change independently from application code.

Inside Compose, `REDIS_URL` uses the service hostname `redis`. Outside
containers, the default remains `redis://localhost:6379/0`.

See [configuration](configuration.md) for ports, authentication, and
startup behavior.

## Verified by actually building and running it

The verification built the image, started the Compose stack, waited for
health checks, and sent a real `POST /recommend` request. The response
matched the serving contract.

Start the stack with:

```bash
docker compose up -d --build kafka redis api
```

See [serving contract](serving-contract.md) and
[health checks](health-checks.md).
