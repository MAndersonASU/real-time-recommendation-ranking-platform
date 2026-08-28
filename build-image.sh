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

if [ -n "$(git status --porcelain)" ]; then
  echo "warning: working tree is not clean -- the image will carry commit" >&2
  echo "  $COMMIT" >&2
  echo "  but may not exactly match what that commit's tree contains." >&2
fi

GIT_COMMIT_SHA="$COMMIT" docker compose build api
