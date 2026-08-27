#!/usr/bin/env bash
#
# Run every evaluation whose report is published, against the artifacts a
# rebuild just produced.
#
#   bash evaluate_all.sh <out-dir>
#
# <out-dir> must be OUTSIDE this repository. Reports are written there, not
# into reports/, so the working tree stays clean for the whole pass and
# each run records an honest source_commit. They are copied into the tree
# afterwards, in a dedicated report-only commit.
#
# Order matters: ablations reads the ranking report to measure its deltas
# against the full model from this same rebuild, and stage comparison
# joins the ranking and reranking reports.
set -euo pipefail

OUT="${1:?usage: bash evaluate_all.sh <out-dir outside the repo>}"
PY="./.venv/Scripts/python.exe"

mkdir -p "$OUT"
LOG="$OUT/evaluate.log"

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to evaluate: working tree is not clean" >&2
  git status --porcelain >&2
  exit 1
fi

COMMIT="$(git rev-parse HEAD)"
: > "$LOG"
echo "evaluation commit: $COMMIT" | tee -a "$LOG"
date -u +"started:           %Y-%m-%dT%H:%M:%SZ" | tee -a "$LOG"

run() {
  local name="$1"; shift
  echo "" | tee -a "$LOG"
  echo "=== $name ===" | tee -a "$LOG"
  date -u +"    %H:%M:%SZ" | tee -a "$LOG"
  "$@" >>"$LOG" 2>&1
  echo "    ok" | tee -a "$LOG"
}

run "1/7 baselines"        $PY -m recommender.evaluation.evaluate_baseline  --output-dir "$OUT"
run "2/7 ranking"          $PY -m recommender.evaluation.evaluate_ranking   --output-dir "$OUT"
run "3/7 reranking"        $PY -m recommender.evaluation.evaluate_reranking --output-dir "$OUT"
run "4/7 ablations"        $PY -m recommender.evaluation.ablations          --output-dir "$OUT"
run "5/7 stage comparison" $PY -m recommender.evaluation.stage_comparison   --output-dir "$OUT"
run "6/7 failure analysis" $PY -m recommender.evaluation.failure_analysis   --output-dir "$OUT"
run "7/7 serving latency"  $PY -m recommender.serving.verify_latency        --output-dir "$OUT"

echo "" | tee -a "$LOG"
echo "=== EVALUATIONS COMPLETE ===" | tee -a "$LOG"
date -u +"finished: %Y-%m-%dT%H:%M:%SZ" | tee -a "$LOG"
ls -1 "$OUT"/*.json | tee -a "$LOG"

if [ -n "$(git status --porcelain)" ]; then
  echo "WARNING: the evaluation pass dirtied the working tree" | tee -a "$LOG"
  git status --porcelain | tee -a "$LOG"
fi
