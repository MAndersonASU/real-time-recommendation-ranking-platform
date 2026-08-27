#!/usr/bin/env bash
#
# Rebuild every licensed-data artifact from the current commit.
#
#   bash rebuild.sh <out-dir>
#
# <out-dir> must be OUTSIDE this repository. The log and the build receipt
# are written there, never into the tree. The receipt is copied to
# provenance/build-receipt.json in the commit that publishes the reports;
# reports/ holds evaluation reports only.
#
# Why: `recommender.evaluation.reports.validate` refuses a report produced
# from a dirty working tree, and untracked files count as dirty -- an
# uncommitted script is as absent from the recorded commit as an edited
# one. Writing a log or a receipt into the tree part-way through would
# make every evaluation after it refuse to publish. Artifacts themselves
# are safe because data/ is gitignored.
#
# This script must already be committed before the build that its receipt
# describes. Committing it afterwards, even unchanged, does not establish
# that its commit produced the artifacts: nothing rules out an edit
# between the run and the commit.
set -euo pipefail

OUT="${1:?usage: bash rebuild.sh <out-dir outside the repo>}"
PY="./.venv/Scripts/python.exe"

mkdir -p "$OUT"
LOG="$OUT/rebuild.log"
RECEIPT="$OUT/build-receipt.json"

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to build: working tree is not clean" >&2
  git status --porcelain >&2
  exit 1
fi

COMMIT="$(git rev-parse HEAD)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

: > "$LOG"
echo "build commit: $COMMIT" | tee -a "$LOG"
echo "started:      $STARTED" | tee -a "$LOG"

step() {
  echo "" | tee -a "$LOG"
  echo "=== $* ===" | tee -a "$LOG"
  date -u +"    %H:%M:%SZ" | tee -a "$LOG"
}

step "1/6 ingest MIND-small from data/raw"
$PY -m recommender.data.ingest >>"$LOG" 2>&1

step "2/6 build time-aware splits"
$PY -m recommender.data.make_splits >>"$LOG" 2>&1

step "3/6 train two-tower retrieval model (content vectors + manifest)"
$PY -m recommender.retrieval.train >>"$LOG" 2>&1

step "4/6 build Faiss index"
$PY -m recommender.retrieval.build_index >>"$LOG" 2>&1

step "5/6 build ranking dataset"
$PY -m recommender.ranking.build_dataset >>"$LOG" 2>&1

step "6/6 train ranking model"
$PY -m recommender.ranking.train >>"$LOG" 2>&1

FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
step "writing build receipt"
$PY -m recommender.evaluation.build_receipt \
    --output "$RECEIPT" \
    --script rebuild.sh \
    --started "$STARTED" \
    --finished "$FINISHED" >>"$LOG" 2>&1

echo "" | tee -a "$LOG"
echo "=== REBUILD COMPLETE ===" | tee -a "$LOG"
echo "finished: $FINISHED" | tee -a "$LOG"
echo "receipt:  $RECEIPT" | tee -a "$LOG"

if [ -n "$(git status --porcelain)" ]; then
  echo "WARNING: the build dirtied the working tree" | tee -a "$LOG"
  git status --porcelain | tee -a "$LOG"
fi
