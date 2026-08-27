# Containerizing Services

A real, running Docker Compose topology for the multi-service platform:
Kafka, Redis, and — for the first time — an actual HTTP API process
wrapping the recommendation pipeline. Implementation: `Dockerfile`,
`docker-compose.yml`, `src/recommender/serving/app.py`.

## The first real API process this project has stood up

Every component since the serving path called `recommend()`/`safe_recommend()`
directly, as a Python function — real, but never reachable over a
network. `app.py` is a thin FastAPI wrapper: one `POST /recommend`
endpoint validated by the exact same `RecommendationRequest`/
`RecommendationResponse` contract (`docs/operations/serving-contract.md`), and a
lifespan hook that calls `build_serving_context()` once at process
start, the same context every test and verification script already
uses — not a second, app-specific load path.

## Data stays out of the image, on purpose

The trained model, the Faiss index, the ranking pipeline, and the
reserved splits are gitignored local research output — never committed,
never meant to be reproduced by anyone without running the licensed
dataset's own pipeline first (`docs/dataset-source.md`). Baking any of
that into the Docker image would either violate that boundary or bloat
the image with data that changes independently of the code. `data/` is
mounted as a read-only volume in `docker-compose.yml` instead, treating
model artifacts the way this project has always treated them: real,
external, versioned separately from the code that consumes them.

## Configuration, minimally, ahead of its own dedicated component

The API container needs to reach Redis by its Compose service name
(`redis`), not `localhost` — the address every other caller in this
project already defaults to. `app.py` reads `REDIS_URL` from the
environment, falling back to the existing `localhost` default so every
non-containerized caller (tests, verify scripts) is unaffected. This is
deliberately minimal: real environment-based configuration, secret
handling, and startup-dependency validation are handled in
`docs/operations/configuration.md`.

## Verified by actually building and running it

The image was built and started via `docker compose up`, alongside the
real Kafka and Redis containers this project has run since the streaming pipeline and online
feature store were built, and a real HTTP request against the running container's
`/recommend` endpoint returned a valid, contract-conforming response —
not just a file written and assumed to work.
