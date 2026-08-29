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

# Anchored to this script's own directory, not the caller's cwd:
# every command below (git status/rev-parse, docker compose reading
# docker-compose.yml) is otherwise relative to wherever this script
# happens to be invoked from, found by direct reproduction -- running
# it from an unrelated directory failed outright ("not a git
# repository") instead of operating on this repository, and from
# inside a *different* git repository it would silently have read that
# repository's commit and status rather than this one's.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMMIT="$(git rev-parse HEAD)"

# Refuses any dirty build outright, rather than warning and continuing
# or trying to enumerate every path that happens to affect the image
# today. An earlier version checked only src/, Dockerfile,
# pyproject.toml and requirements-lock.txt -- real gaps, since
# docker-compose.yml (the build context, args and Dockerfile path are
# all defined there), .dockerignore (controls what actually reaches
# the build context) and any Compose override file are just as
# image-affecting and were not checked at all. Requiring the *entire*
# working tree clean is the safer rule: it cannot miss a build input
# this list forgot to name, today or after a future change to the
# build. A change to something that doesn't affect the image at all
# (this script, most of docs/) still blocks a build under this rule --
# a real, accepted cost for not depending on an enumerated list staying
# complete, the same trade this project's evaluation-report provenance
# check already makes (`recommender.evaluation.reports.working_tree_is_clean`
# refuses a dirty tree outright, not just a dirty subset of it).
DIRTY_FILES="$(git status --porcelain)"

if [ -n "$DIRTY_FILES" ]; then
  echo "refusing to build: the working tree is not clean (uncommitted or" >&2
  echo "untracked changes) relative to commit $COMMIT:" >&2
  echo "$DIRTY_FILES" >&2
  echo "" >&2
  echo "Docker would copy the actual working-tree contents into the image while it" >&2
  echo "is labeled with commit $COMMIT, which would not describe what the image" >&2
  echo "really contains. Commit the changes first, or stash/discard them, then" >&2
  echo "rerun." >&2
  exit 1
fi

GIT_COMMIT_SHA="$COMMIT" docker compose build api
