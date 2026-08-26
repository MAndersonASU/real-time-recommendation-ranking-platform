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
import re
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
    """True when nothing outside `reports/` is modified, staged or
    untracked.

    Untracked files count, not just modified ones: a report produced with
    an uncommitted evaluation script sitting in the tree is not
    reproducible from the recorded commit, and an untracked script is
    exactly as absent from that commit as an edited one.

    `reports/` is excluded because it is this run's own output. A full
    evaluation pass publishes several reports, and without the exclusion
    the first one written would dirty the tree and make every later one
    refuse -- the check would be blocking correct behaviour rather than
    incorrect code. Nothing else is exempt; the question the rule exists
    to answer is whether the recorded commit describes the code that ran,
    and writing results does not change that answer.
    """
    status = _git("status", "--porcelain", "--", ".", ":(exclude)reports")
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

    undefined = sorted(_metric_leaves(results) - set(definitions))
    if undefined:
        raise ValueError(
            f"results contain metrics with no definition: {undefined}. Every published "
            f"measurement needs one, at any depth. If one of these is metadata rather "
            f"than a measurement, add it to _METADATA_KEYS so the exemption is "
            f"explicit and reviewable."
        )

    denominators = report["denominators"]
    if not isinstance(denominators, dict) or not denominators:
        raise ValueError("report has no denominators")
    null_denominators = [k for k, v in denominators.items() if v is None]
    if null_denominators:
        raise ValueError(
            f"denominators must not be null -- a rate with no denominator cannot be "
            f"interpreted: {sorted(null_denominators)}"
        )

    _validate_metric_values(results)

    _validate_fit_only_provenance(report)

    if not isinstance(report["limitations"], list):
        raise TypeError("limitations must be a list, even if empty")
    if not isinstance(report["sampling"], dict) or not report["sampling"]:
        raise ValueError("report must state how its sample was selected")
    for key in ("dataset", "artifacts", "configuration"):
        if not isinstance(report[key], dict):
            raise TypeError(f"{key} must be an object")


_FIT_ONLY_REQUIRED_HASHES = (
    "retrieval_model_sha256",
    "content_artifact_sha256",
    "bundle_manifest_sha256",
    "ranking_feature_table_sha256",
    "train_report_sha256",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_fit_only_provenance(report: dict) -> None:
    """A leakage-free claim must identify the artifacts behind it.

    `tune_fold_leakage: false` says a tuning comparison used a retrieval
    model that never saw the fold. That is only checkable if the report
    names the model. An earlier version recorded the string "absent" for
    a missing artifact and validation accepted it, so the strongest
    claim in the report could be published with nothing identifying its
    subject.

    Enforced only when the claim is actually made: a run that used the
    deployed table reports `tune_fold_leakage: true`, and is not
    required to carry a fit-only manifest because it does not have one.
    """
    results = report.get("results")
    if not isinstance(results, dict):
        return

    claims_leakage_free = any(
        isinstance(section, dict)
        and section.get("feature_provenance", {}).get("tune_fold_leakage") is False
        for section in results.values()
    )
    if not claims_leakage_free:
        return

    bundle = report.get("artifacts", {}).get("fit_only_bundle")
    if bundle is None:
        raise ValueError(
            "report claims tune_fold_leakage: false but carries no fit_only_bundle "
            "manifest, so the model behind the claim is unidentified"
        )
    if not isinstance(bundle, dict):
        raise TypeError(f"fit_only_bundle must be an object, got {type(bundle).__name__}")

    for field in _FIT_ONLY_REQUIRED_HASHES:
        value = bundle.get(field)
        if not isinstance(value, str) or not _SHA256_PATTERN.match(value):
            raise ValueError(
                f"fit_only_bundle.{field} is {value!r}, which does not identify an "
                f"artifact. A leakage-free claim requires a full lowercase SHA-256 "
                f"for every fit-only artifact."
            )

    for field, kind in (
        ("tune_fold_seed", int),
        ("training_seed", int),
        ("embedding_dim", int),
        ("tune_fold_fraction", float),
    ):
        value = bundle.get(field)
        if not isinstance(value, kind) or isinstance(value, bool):
            raise TypeError(
                f"fit_only_bundle.{field} must be a {kind.__name__}, got {value!r}"
            )
    if not 0.0 < bundle["tune_fold_fraction"] < 1.0:
        raise ValueError(
            f"fit_only_bundle.tune_fold_fraction is {bundle['tune_fold_fraction']}, "
            f"which does not describe a fold"
        )


# Keys that describe a run rather than measure it: seeds, digests,
# counts of what was sampled, echoes of configuration, prose. They are
# published and they are useful, but they are not results and there is
# nothing to define about them.
#
# The list is explicit rather than heuristic. A rule like "anything
# ending in _rate is a metric" would silently exempt whatever it failed
# to match, which is the failure this whole check exists to prevent:
# an invented nested field named `made_up_score` passed validation
# because only top-level keys were compared against the definitions.
_METADATA_KEYS = frozenset(
    {
        # provenance and sampling description
        "seed", "method", "note", "sampling", "shared_samples", "sharing_note",
        "by_comparison", "selected_ids_sha256", "selected_ids_sha256_prefix",
        "selected_impressions", "eligible_impressions", "selected_fraction",
        "distinct_users", "time_range", "start", "end",
        "user_and_time_metadata",
        # what was compared, and on what
        "selection_rule", "split", "purpose", "bundle", "feature_provenance",
        "feature_table", "retrieval_model_trained_on", "feature_context_fitted_on",
        "tune_fold_leakage", "sample_impressions", "impressions_checked",
        "impressions_measured", "fit_rows", "tune_rows",
        # echoes of deployed configuration, not measurements of it
        "currently_configured_cap", "currently_configured_depth",
        "currently_configured_min_fresh_in_slate", "currently_configured_threshold_days",
        "budgets_supporting_current_configuration", "search_p99_budget_ms",
        "depths_within_search_budget",
        # explanation-layer counts that name themselves
        "explanations_evaluated",
    }
)


def _is_dimension_key(key: str) -> bool:
    """True for a key that names a *value being compared*, not a metric.

    Comparison tables are keyed by the candidate value -- budgets
    `"0.90"`, caps `"3"`, retrieval depths `"1000"`. Those keys are
    coordinates in the table, and demanding a definition for each one
    would mean defining every number anyone ever compares.
    """
    try:
        float(key)
    except (TypeError, ValueError):
        return False
    return True


def _metric_leaves(node, inside_metadata: bool = False) -> set:
    """Every published measurement's key name, at any depth.

    Descends into comparison tables and lists, so
    `by_min_fresh_value.2.mean_slate_relevance` contributes
    `mean_slate_relevance`. Stops at metadata subtrees, because a
    sampling block's internals are description, not results.
    """
    found: set = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _METADATA_KEYS:
                continue
            if isinstance(value, (dict, list)):
                found |= _metric_leaves(value, inside_metadata)
            elif not _is_dimension_key(key):
                found.add(key)
    elif isinstance(node, list):
        for item in node:
            found |= _metric_leaves(item, inside_metadata)
    return found


def _is_rate(metric_name: str) -> bool:
    return any(
        token in metric_name
        for token in ("rate", "recall", "ndcg", "mrr", "coverage", "precision")
    )


# Keys whose values are descriptive metadata rather than measurements:
# seeds, digests, counts, prose. A range check on them would be
# meaningless, and some legitimately carry values outside [0, 1].
_NON_METRIC_KEYS = frozenset(
    {
        "seed",
        "method",
        "note",
        "selection_rule",
        "split",
        "feature_provenance",
        "sampling",
        "time_range",
        "purpose",
        "bundle",
    }
)


# Keys whose subtree may legitimately contain null. A selection rule
# that finds no value satisfying a budget reports null, and that null is
# the answer -- "no cap retains 99% of relevance" is a real result, not a
# missing measurement. Distinguishing the two is the whole point: a null
# denominator makes a rate uninterpretable, while a null selection is
# itself interpretable.
_NULLABLE_SUBTREE_KEYS = frozenset(
    {
        "cap_selected_by_relevance_budget",
        "value_selected_by_relevance_budget",
        "selected_by_relevance_budget",
        "depth_selected_by_latency_budget",
    }
)


def _validate_metric_values(node, path: str = "", nulls_allowed: bool = False) -> None:
    """Checks every metric in the tree, not just the top level.

    The tuning report's results are nested decision objects: almost none
    of its rates live at the top level. A non-recursive check therefore
    inspected a handful of section names and passed everything that
    mattered -- a nested rate of 9.0 was accepted, which is how this gap
    was found.

    Traversal stops at descriptive metadata (`_NON_METRIC_KEYS`) because
    a seed or an id is not a measurement and has no range to violate.
    Lists are walked too: a tradeoff table is a list of per-value
    objects, and its rates are as publishable as any other.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key in _NON_METRIC_KEYS:
                continue
            allowed = nulls_allowed or key in _NULLABLE_SUBTREE_KEYS
            if value is None and not allowed:
                raise ValueError(
                    f"metric {here!r} is null. If null is the intended answer -- a "
                    f"selection rule that nothing satisfied -- its key belongs in "
                    f"_NULLABLE_SUBTREE_KEYS so the distinction stays explicit."
                )
            is_numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            if _is_rate(key) and is_numeric and not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"metric {here!r} is a rate but has value {value}")
            _validate_metric_values(value, here, allowed)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _validate_metric_values(item, f"{path}[{index}]", nulls_allowed)


def write_report(report: dict, directory: Path = REPORTS_DIR) -> Path:
    validate_report(report)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['report_name']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
