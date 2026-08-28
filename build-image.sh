#!/usr/bin/env bash
#
# Builds the API image with a real Git commit identity baked in.
#
#   bash build-image.sh
#
# Compose can't run a shell command inline for a build arg, so
# `docker-compose.yml`'s `api.build.args.GIT_COMMIT_SHA` only forwards
# whatever is already in the host environment when Compose runs -- a
# plain `docker compose build api`, with no wrapper, builds an image
# whose GIT_COMMIT_SHA is unset (DEPLOYMENT-CONTRACT-62: the Dockerfile
# used to claim Compose supplied this "automatically", which was never
# true). This script is the one place that actually calls `git
# rev-parse HEAD` and passes it through.
#
# `recommender.tracking.experiment_log`'s repository-discovery fallback
# is the only thing this value feeds inside the container (no `.git`
# directory is ever copied in) -- an image built without it still runs
# correctly, it just can't attribute a container-run experiment log
# entry to a commit.
set -euo pipefail

COMMIT="$(git rev-parse HEAD)"

# Refuses a dirty build outright, rather than warning and continuing:
# an uncommitted or untracked change under one of these paths is copied
# into the image by the Dockerfile (`COPY src/ ./src/`,
# `COPY pyproject.toml ./`, `COPY requirements-lock.txt ./`) or changes
# the build recipe itself (Dockerfile), while the image is labeled with
# $COMMIT regardless -- the same provenance mismatch this project
# refuses for an evaluation report from a dirty tree
# (`recommender.evaluation.reports.working_tree_is_clean`), not treated
# any more leniently here just because it's a build script instead of
# a report. A change *outside* these paths (docs, this script itself)
# doesn't affect what the image actually contains, so it's not checked.
DIRTY_IMAGE_FILES="$(git status --porcelain -- src Dockerfile pyproject.toml requirements-lock.txt)"

if [ -n "$DIRTY_IMAGE_FILES" ]; then
  echo "refusing to build: these image-affecting paths are dirty (uncommitted or" >&2
  echo "untracked) relative to commit $COMMIT:" >&2
  echo "$DIRTY_IMAGE_FILES" >&2
  echo "" >&2
  echo "Docker would copy the actual working-tree contents into the image while it" >&2
  echo "is labeled with commit $COMMIT, which would not describe what the image" >&2
  echo "really contains. Commit the changes first, or stash/discard them, then" >&2
  echo "rerun." >&2
  exit 1
fi

GIT_COMMIT_SHA="$COMMIT" docker compose build api
