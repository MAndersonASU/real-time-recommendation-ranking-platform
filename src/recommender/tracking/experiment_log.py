import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_LOG_PATH = Path("data/processed/mind_small/experiment_log.jsonl")


def _current_git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
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
        "logged_at": datetime.now().isoformat(),  # noqa: DTZ005 -- naive, matches every other timestamp in this project
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
