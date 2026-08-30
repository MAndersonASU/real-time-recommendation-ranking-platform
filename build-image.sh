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

# Explicit -f/--project-directory, not a bare "docker compose build
# api": Compose otherwise resolves its config from the *environment*
# (COMPOSE_FILE, an auto-discovered docker-compose.override.yml) as
# much as from this directory, and none of that is covered by the
# clean-tree check above -- COMPOSE_FILE naming a file outside this
# repository (including one set from the gitignored .env, which
# Compose reads automatically) never appears in "git status" here.
# Reproduced directly: with COMPOSE_FILE pointed at an unrelated
# compose file, a bare "docker compose config" built its plan from
# that file entirely, silently. Pinning both flags to this script's
# own directory means the committed docker-compose.yml is the only
# configuration this script can ever build from, regardless of what
# COMPOSE_FILE or an override file elsewhere names.
#
# -p recommender: with no explicit project name, Compose derives one
# from the checkout directory's own basename and appends "-api" to
# form the image tag -- found to fail outright when that basename ends
# in an underscore ("invalid tag \"...hz_-api\": invalid reference
# format"), reproduced directly against a real checkout with such a
# name. A real deployment's checkout directory is exactly as
# unpredictable as that, so pinning a fixed, always-valid project name
# removes the dependency on it entirely, the same reasoning that
# already anchors -f/--project-directory above rather than trusting
# ambient state.
GIT_COMMIT_SHA="$COMMIT" docker compose \
  -f "$SCRIPT_DIR/docker-compose.yml" \
  --project-directory "$SCRIPT_DIR" \
  -p recommender \
  build api
