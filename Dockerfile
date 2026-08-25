# Pinned by digest, not just by tag: `python:3.11-slim` is a moving
# target that is rebuilt regularly, so a tag-only base means two builds
# of the same commit can contain different system libraries. The digest
# makes the base image part of what the lock file guarantees.
# Corresponds to python:3.11-slim as of 2026-08-25.
FROM python@sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7

WORKDIR /app

# Dependencies come from the hash-verified lock, in their own layer so a
# source-only change does not trigger a full reinstall.
COPY requirements-lock.txt ./

# --require-hashes, matching the locked-install CI job exactly. Installing
# with `pip install .` here instead would re-resolve dependencies at build
# time, so the container could ship a different dependency set from the
# one CI actually tested -- the versions would drift apart silently, and
# only in the artifact that actually gets deployed.
#
# The lock is Linux/CPU-only (see requirements-lock.txt), which matches
# this base image and this project's CPU-only design.
RUN pip install --no-cache-dir --require-hashes -r requirements-lock.txt

COPY pyproject.toml ./
COPY src/ ./src/

# --no-deps: every dependency is already installed above, hash-verified.
# Without this, installing the project would let pip resolve and pull
# replacements outside the lock.
RUN pip install --no-cache-dir --no-deps .

# This image has no .git directory at all (only pyproject.toml and
# src/ are copied in above), so recommender.tracking.experiment_log's
# repository-discovery fallback would always resolve to None here --
# passed in at build time instead, from a real `git rev-parse HEAD`
# (docker-compose.yml's api build.args does this automatically).
ARG GIT_COMMIT_SHA=""
ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

# Where the data actually live in this image. Required, not optional.
#
# recommender.paths anchors data to the repository root so a serving
# version cannot change with the caller's working directory. That
# anchor is computed from the package's own location, which is correct
# for a source checkout and wrong here: the package is installed into
# site-packages, so the repository-root walk lands on
# /usr/local/lib/python3.11 and every artifact resolves under a
# directory that has never held any data.
#
# This is the override recommender.paths.data_root() exists for. It
# also decouples the image from wherever pip happens to install the
# package, which a relative path from WORKDIR would not.
ENV RECOMMENDER_DATA_ROOT=/app/data

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
