"""Machine-readable evaluation reports with provenance.

Every quality number this project publishes comes from the licensed
MIND dataset, which is never redistributed here. A reader of a public
clone therefore cannot re-derive those numbers, and a bare figure in
prose is not independently checkable.

These reports are the closest honest substitute: license-safe aggregate
results, each stamped with the exact commit, artifact hashes,
configuration and seeds that produced it, plus the denominators and
metric definitions needed to interpret it. They do not make the numbers
reproducible without the dataset -- nothing can -- but they make it
possible to see precisely what was measured, under what conditions, and
whether a published figure still corresponds to the current code.

Nothing dataset-derived beyond aggregate metrics is written: no rows,
no user identifiers, no article text.
"""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPORTS_DIR = Path("reports")

# Bumped when the shape or meaning of a report changes, so an old
# committed report is never silently read as if it followed the current
# contract.
REPORT_SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "report_name",
    "schema_version",
    "source_commit",
    "generated_at",
    "dataset",
    "artifacts",
    "configuration",
    "denominators",
    "metric_definitions",
    "results",
    "limitations",
)


def _source_commit() -> str:
    from_env = os.environ.get("GIT_COMMIT_SHA")
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def build_report(
    report_name: str,
    dataset: dict,
    configuration: dict,
    denominators: dict,
    metric_definitions: dict,
    results: dict,
    limitations: list,
) -> dict:
    """Assembles one report. `artifacts` comes from the serving manifest
    so a report is tied to the exact artifacts that produced it, and a
    later artifact change is visible as a changed hash rather than an
    unexplained metric shift.
    """
    from recommender.monitoring.artifact_manifest import build_serving_artifact_manifest

    return {
        "report_name": report_name,
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_commit": _source_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": dataset,
        "artifacts": build_serving_artifact_manifest(),
        "configuration": configuration,
        "denominators": denominators,
        "metric_definitions": metric_definitions,
        "results": results,
        "limitations": limitations,
    }


def validate_report(report: dict) -> None:
    """Raises if a report does not satisfy the documented contract.

    Enforced rather than trusted: a report missing its provenance is
    worse than no report, because it looks authoritative while being
    unattributable.
    """
    missing = [field for field in REQUIRED_FIELDS if field not in report]
    if missing:
        raise ValueError(f"report is missing required fields: {missing}")

    if report["schema_version"] != REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"report schema version {report['schema_version']} does not match the current "
            f"contract version {REPORT_SCHEMA_VERSION}"
        )
    if not isinstance(report["results"], dict) or not report["results"]:
        raise ValueError("report has no results")
    if not isinstance(report["limitations"], list):
        raise TypeError("limitations must be a list, even if empty")
    for key in ("dataset", "artifacts", "configuration", "denominators", "metric_definitions"):
        if not isinstance(report[key], dict):
            raise TypeError(f"{key} must be an object")


def write_report(report: dict, directory: Path = REPORTS_DIR) -> Path:
    validate_report(report)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['report_name']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
