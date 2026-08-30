#!/usr/bin/env bash
#
# Run every published evaluation, against the artifacts a rebuild just
# produced.
#
#   bash evaluate_all.sh <out-dir>
#
# <out-dir> must be OUTSIDE this repository. Reports are written there, not
# into reports/, so the working tree stays clean for the whole pass and
# each run records an honest source_commit. They are copied into the tree
# afterwards, in a dedicated report-only commit.
#
# Order matters in two places: ablations reads the ranking report to
# measure its deltas against the full model from this same rebuild, and
# stage comparison joins the ranking and reranking reports. Everything
# else here is independent and could run in any order.
#
# tuning-decisions needs the fit-only bundle (`rebuild.sh`'s last two
# steps) to publish a leakage-free comparison; run rebuild.sh first, on
# the same commit, or this step falls back to a leaked comparison and
# says so in the published report.
set -euo pipefail

OUT="${1:?usage: bash evaluate_all.sh <out-dir outside the repo>}"

if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"      # Windows venv layout
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"              # macOS / Linux venv layout
else
  echo "no .venv found at .venv/Scripts/python.exe or .venv/bin/python -- " \
       "create one first (see README's Setup section)" >&2
  exit 1
fi

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

run "1/13 retrieval"          $PY -m recommender.evaluation.evaluate_retrieval        --output-dir "$OUT"
run "2/13 baselines"          $PY -m recommender.evaluation.evaluate_baseline         --output-dir "$OUT"
run "3/13 ranking"            $PY -m recommender.evaluation.evaluate_ranking          --output-dir "$OUT"
run "4/13 reranking"          $PY -m recommender.evaluation.evaluate_reranking        --output-dir "$OUT"
run "5/13 end-to-end"         $PY -m recommender.evaluation.evaluate_end_to_end       --output-dir "$OUT"
run "6/13 explanations"       $PY -m recommender.evaluation.evaluate_explanations     --output-dir "$OUT"
run "7/13 ablations"          $PY -m recommender.evaluation.ablations                 --output-dir "$OUT"
run "8/13 stage comparison"   $PY -m recommender.evaluation.stage_comparison          --output-dir "$OUT"
run "9/13 failure analysis"   $PY -m recommender.evaluation.failure_analysis          --output-dir "$OUT"
run "10/13 tuning decisions"  $PY -m recommender.evaluation.verify_tuning_decisions   --output-dir "$OUT"
run "11/13 min-fresh experiment" $PY -m recommender.evaluation.min_fresh_experiment   --output-dir "$OUT"
run "12/13 serving latency"   $PY -m recommender.serving.verify_latency               --output-dir "$OUT"
run "13/13 durable-history fallback" $PY -m recommender.evaluation.evaluate_durable_history_fallback --output-dir "$OUT"

echo "" | tee -a "$LOG"
echo "=== EVALUATIONS COMPLETE ===" | tee -a "$LOG"
date -u +"finished: %Y-%m-%dT%H:%M:%SZ" | tee -a "$LOG"
ls -1 "$OUT"/*.json | tee -a "$LOG"

if [ -n "$(git status --porcelain)" ]; then
  echo "WARNING: the evaluation pass dirtied the working tree" | tee -a "$LOG"
  git status --porcelain | tee -a "$LOG"
fi
