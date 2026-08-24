FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# This image has no .git directory at all (only pyproject.toml and
# src/ are copied in above), so recommender.tracking.experiment_log's
# repository-discovery fallback would always resolve to None here --
# passed in at build time instead, from a real `git rev-parse HEAD`
# (docker-compose.yml's api build.args does this automatically).
ARG GIT_COMMIT_SHA=""
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

# Runs as a real, unprivileged user rather than root -- no part of this
# process (serving live HTTP traffic) needs root, so it doesn't run as
# root. /app/data is where the model/index/ranking-pipeline volume gets
# mounted at runtime (below); owned by the app user so the mounted
# volume is actually readable.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000

# data/ (the trained model, index, ranking pipeline, and licensed
# dataset) is never baked into the image -- it's gitignored local
# research output, mounted as a volume at runtime instead, the same
# way this project has always treated it as external, reproducible-
# from-source artifacts rather than something to ship inside a build.
#
# `sh -c "exec ..."`, not a bare shell-form CMD: still lets
# `${API_PORT:-8000}` expand (API_PORT is real, explicit, environment-
# based configuration, docs/configuration.md), but `exec` replaces the
# shell process with uvicorn itself instead of running it as a child --
# so a real `docker stop`'s SIGTERM reaches uvicorn directly for a clean
# shutdown, instead of being sent to a shell that may not forward it.
CMD ["sh", "-c", "exec uvicorn recommender.serving.app:app --host 0.0.0.0 --port ${API_PORT:-8000}"]
