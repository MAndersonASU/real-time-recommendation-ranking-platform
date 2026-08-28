import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from recommender.paths import mind_small_path

DEFAULT_LOG_PATH = mind_small_path("experiment_log.jsonl")

# This file's own location anchors the git command to this project's
# repo, not wherever the calling process's current working directory
# happens to be. `git rev-parse HEAD` with no explicit `cwd` resolves
# relative to the *process's* cwd -- if a caller (a script launched from
# a different directory, a notebook, a different working directory
# inside a container) invokes `log_run` from outside this repo, or from
# inside a *different* git repo entirely, this would silently record
# that other repo's commit (or None) as if it were this project's own
# reproducibility identity.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _current_git_commit() -> str | None:
    """Prefers the real, documented `GIT_COMMIT_SHA` environment
    variable over discovering it from a local `.git` directory.
    Repository discovery is a real fallback for local development, but
    a container image built from a source archive (no `.git` directory
    at all -- the Dockerfile only copies `pyproject.toml` and `src/`) or
    a wheel install would always resolve to `None` there, losing this
    project's own reproducibility identity in exactly the deployed
    environment where it matters most. `docker-compose.yml`'s `api`
    build passes this through from a real `git rev-parse HEAD` at build
    time.
    """
    env_commit = os.environ.get("GIT_COMMIT_SHA")
    if env_commit:
        return env_commit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, cwd=_PROJECT_ROOT
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def log_run(
    run_name: str,
    params: dict,
    metrics: dict,
    notes: str = "",
    path: Path = DEFAULT_LOG_PATH,
) -> dict:
    """Appends one experiment record to an append-only JSONL log: a run
    name, its parameters (split, K, model config), its metrics, free-text
    notes, and the exact git commit the project was at when the run was
    recorded -- real reproducibility identity (docs/experiment-
    tracking.md explains why this is a plain log rather than MLflow).
    """
    record = {
        "run_name": run_name,
        "logged_at": datetime.now(UTC).isoformat(),
        "git_commit": _current_git_commit(),
        "params": params,
        "metrics": metrics,
        "notes": notes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def load_runs(path: Path = DEFAULT_LOG_PATH) -> pd.DataFrame:
    """Every logged run, flattened into one row per run with each metric
    and param as its own column -- the actual "reduce manual tracking"
    payoff a tracking tool is supposed to provide: comparing every
    experiment's numbers side by side becomes one function call instead
    of opening N separate report files by hand.
    """
    if not path.exists():
        return pd.DataFrame()
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = []
    for record in records:
        row = {
            "run_name": record["run_name"],
            "logged_at": record["logged_at"],
            "git_commit": record["git_commit"],
            "notes": record["notes"],
        }
        row.update({f"param_{k}": v for k, v in record["params"].items()})
        row.update({f"metric_{k}": v for k, v in record["metrics"].items()})
        rows.append(row)
    return pd.DataFrame(rows)
