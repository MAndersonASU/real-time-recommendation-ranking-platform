"""Machine-readable evaluation reports with verifiable provenance.

Every quality number this project publishes comes from the licensed MIND
dataset, which is never redistributed. A reader of a public clone cannot
re-derive them, so a bare figure in prose is not checkable.

These reports are the closest honest substitute: license-safe aggregate
results, each stamped with what actually produced them. Two properties
make that stamp meaningful, and the earlier version had neither:

- **Written during the run.** Reports used to be assembled afterwards by
  reading previously produced JSON and attaching the *current* commit and
  manifest. Nothing established that the current code produced those
  numbers -- an edit between the run and the publish step would silently
  mislabel stale results as current. `build_report` is now called by the
  evaluation itself while it holds the results.
- **Refused from a dirty tree.** A commit hash describes uncommitted code
  inaccurately by definition. Publishing from a modified working tree is
  rejected rather than recorded with a caveat nobody reads.

Nothing dataset-derived beyond aggregate metrics is written: no rows, no
user identifiers, no article text.
"""

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from recommender.paths import PROJECT_ROOT

REPORTS_DIR = PROJECT_ROOT / "reports"

# Bumped when the shape or meaning of a report changes, so an old
# committed report is never silently read as if it followed the current
# contract.
REPORT_SCHEMA_VERSION = 2

REQUIRED_FIELDS = (
    "report_name",
    "schema_version",
    "provenance",
    "dataset",
    "artifacts",
    "configuration",
    "sampling",
    "denominators",
    "metric_definitions",
    "results",
    "limitations",
)

REQUIRED_PROVENANCE_FIELDS = (
    "source_commit",
    "working_tree_clean",
    "generated_at",
    "evaluation_module",
)


class ReportProvenanceError(RuntimeError):
    """A report cannot be attributed to a specific, committed state.

    Fatal rather than a warning: a report whose provenance is wrong looks
    authoritative while being unattributable, which is worse than having
    no report.
    """


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True, timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def source_commit() -> str | None:
    return os.environ.get("GIT_COMMIT_SHA") or _git("rev-parse", "HEAD")


def working_tree_is_clean() -> bool:
    """True when nothing is modified, staged or untracked.

    Untracked files count: a report produced with an uncommitted
    evaluation script sitting in the tree is not reproducible from the
    recorded commit.
    """
    status = _git("status", "--porcelain")
    if status is None:
        return False
    return status == ""


def file_digest(path: Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_fingerprints() -> dict:
    """Digests of the split files an evaluation reads, so a report names
    the exact data behind it rather than only the dataset's title.
    """
    from recommender.evaluation.contract import CATALOG_PATH, SPLITS_DIR

    fingerprints = {"catalog_sha256": file_digest(CATALOG_PATH)}
    for split in ("train", "validation", "replay"):
        fingerprints[f"{split}_sha256"] = file_digest(SPLITS_DIR / split / "behaviors.parquet")
    return fingerprints


def build_report(
    report_name: str,
    evaluation_module: str,
    dataset: dict,
    configuration: dict,
    sampling: dict,
    denominators: dict,
    metric_definitions: dict,
    results: dict,
    limitations: list,
    require_clean_tree: bool = True,
) -> dict:
    """Assembles one report at the moment its results were produced.

    `require_clean_tree` exists only so tests can build a report without
    committing; every real evaluation leaves it on.
    """
    from recommender.monitoring.artifact_manifest import build_serving_artifact_manifest

    clean = working_tree_is_clean()
    if require_clean_tree and not clean:
        raise ReportProvenanceError(
            "refusing to build a report from a dirty working tree: the recorded "
            "commit would not describe the code that produced these results. "
            "Commit the evaluation code first, then rerun."
        )

    return {
        "report_name": report_name,
        "schema_version": REPORT_SCHEMA_VERSION,
        "provenance": {
            "source_commit": source_commit(),
            "working_tree_clean": clean,
            "generated_at": datetime.now(UTC).isoformat(),
            "evaluation_module": evaluation_module,
        },
        "dataset": {**dataset, **split_fingerprints()},
        "artifacts": build_serving_artifact_manifest(),
        "configuration": configuration,
        "sampling": sampling,
        "denominators": denominators,
        "metric_definitions": metric_definitions,
        "results": results,
        "limitations": limitations,
    }


def validate_report(report: dict) -> None:
    """Enforces the report contract.

    Every rule here corresponds to a way an earlier report was
    unusable: missing provenance, null denominators that made a rate
    uninterpretable, metrics with no definition, and values outside the
    range their definition implies.
    """
    missing = [field for field in REQUIRED_FIELDS if field not in report]
    if missing:
        raise ValueError(f"report is missing required fields: {missing}")

    if report["schema_version"] != REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"report schema version {report['schema_version']} does not match the "
            f"current contract version {REPORT_SCHEMA_VERSION}"
        )

    provenance = report["provenance"]
    if not isinstance(provenance, dict):
        raise TypeError("provenance must be an object")
    missing_provenance = [f for f in REQUIRED_PROVENANCE_FIELDS if f not in provenance]
    if missing_provenance:
        raise ValueError(f"provenance is missing: {missing_provenance}")
    if not provenance.get("source_commit"):
        raise ValueError("provenance has no source commit")
    if provenance.get("working_tree_clean") is not True:
        raise ValueError(
            "report was produced from a dirty working tree, so its recorded commit "
            "does not describe the code that produced it"
        )

    results = report["results"]
    if not isinstance(results, dict) or not results:
        raise ValueError("report has no results")

    definitions = report["metric_definitions"]
    if not isinstance(definitions, dict):
        raise TypeError("metric_definitions must be an object")

    undefined = [key for key in results if key not in definitions]
    if undefined:
        raise ValueError(f"results contain metrics with no definition: {sorted(undefined)}")

    denominators = report["denominators"]
    if not isinstance(denominators, dict) or not denominators:
        raise ValueError("report has no denominators")
    null_denominators = [k for k, v in denominators.items() if v is None]
    if null_denominators:
        raise ValueError(
            f"denominators must not be null -- a rate with no denominator cannot be "
            f"interpreted: {sorted(null_denominators)}"
        )

    for key, value in results.items():
        if value is None:
            raise ValueError(f"metric {key!r} is null")
        if _is_rate(key) and isinstance(value, (int, float)) and not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"metric {key!r} is a rate but has value {value}")

    if not isinstance(report["limitations"], list):
        raise TypeError("limitations must be a list, even if empty")
    if not isinstance(report["sampling"], dict) or not report["sampling"]:
        raise ValueError("report must state how its sample was selected")
    for key in ("dataset", "artifacts", "configuration"):
        if not isinstance(report[key], dict):
            raise TypeError(f"{key} must be an object")


def _is_rate(metric_name: str) -> bool:
    return any(
        token in metric_name
        for token in ("rate", "recall", "ndcg", "mrr", "coverage", "precision")
    )


def write_report(report: dict, directory: Path = REPORTS_DIR) -> Path:
    validate_report(report)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['report_name']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
