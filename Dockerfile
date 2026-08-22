FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

EXPOSE 8000

# data/ (the trained model, index, ranking pipeline, and licensed
# dataset) is never baked into the image -- it's gitignored local
# research output, mounted as a volume at runtime instead, the same
# way this project has always treated it as external, reproducible-
# from-source artifacts rather than something to ship inside a build.
#
# Shell form, not exec form, so ${API_PORT:-8000} actually expands --
# API_PORT is real, explicit, environment-based configuration
# (docs/configuration.md), not a value hidden inside the image.
CMD uvicorn recommender.serving.app:app --host 0.0.0.0 --port ${API_PORT:-8000}
