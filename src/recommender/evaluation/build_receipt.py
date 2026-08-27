"""Records the chain from a committed build procedure to built artifacts.

    python -m recommender.evaluation.build_receipt --output PATH \
        --started 2026-08-27T01:19:09Z --finished 2026-08-27T01:55:04Z

A report records the commit that computed its numbers. That commit
describes the evaluation code, but on its own it does not say which
artifacts the evaluation read, or that those artifacts were produced by
the same commit rather than left over from an earlier run.

This receipt closes that gap. It is written immediately after a rebuild,
from the tree that performed it, and records:

* the commit the rebuild ran from, and whether its tree was clean
* the SHA-256 of the orchestration script, so a script edited after the
  fact cannot be passed off as the one that ran
* the SHA-256 of every artifact the rebuild produced
* the seeds that made the build deterministic
* when the rebuild started and finished

The chain a reader can then check is:

    committed build procedure -> rebuilt artifacts -> evaluation reports

Committing the script *after* a build, even byte-identically, does not
establish that link: nothing rules out an edit between the run and the
commit. The order that does establish it is to commit the procedure
first, rebuild from that commit, and write this receipt from it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from recommender.paths import mind_small_path

# Every artifact a rebuild produces, relative to the processed data root.
BUILT_ARTIFACTS = (
    "train/news.parquet",
    "splits/train/behaviors.parquet",
    "splits/validation/behaviors.parquet",
    "splits/replay/behaviors.parquet",
    "ranking/train.parquet",
    "ranking/validation.parquet",
    "item_content.npz",
    "two_tower_model.pt",
    "faiss_exact.index",
    "faiss_ivf.index",
    "ranking_model.skops",
    "serving_bundle.json",
)

# Artifacts whose bytes are stable across rebuilds from the same commit.
# ranking_model.skops is deliberately absent: skops embeds bytes that
# differ on every save, so the same training run on identical input
# produces a different file hash while the fitted coefficients are
# identical to the last bit. Its hash is an integrity check for one file,
# not a reproducibility check across rebuilds -- comparing it between
# builds would suggest a model change that did not happen.
BYTE_REPRODUCIBLE = (
    "train/news.parquet",
    "splits/train/behaviors.parquet",
    "splits/validation/behaviors.parquet",
    "splits/replay/behaviors.parquet",
    "item_content.npz",
    "two_tower_model.pt",
)

# Seeds that make the build reproducible. Read from the modules that own
# them rather than restated, so a changed seed cannot silently disagree
# with the receipt.
def _seeds() -> dict:
    from recommender.retrieval.features import CONTENT_SEED
    from recommender.retrieval.train import TRAIN_SEED

    return {
        "retrieval_train_seed": TRAIN_SEED,
        "content_transform_seed": CONTENT_SEED,
    }


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _working_tree_clean() -> bool:
    return _git("status", "--porcelain") == ""


def build_receipt(
    script: Path,
    started: str | None = None,
    finished: str | None = None,
) -> dict:
    processed = Path(mind_small_path())
    return {
        "schema_version": 1,
        "receipt_name": "artifact-build",
        "build_procedure": {
            "script": str(script).replace("\\", "/"),
            "script_sha256": _sha256(script),
        },
        "build_commit": {
            "commit": _git("rev-parse", "HEAD"),
            "working_tree_clean": _working_tree_clean(),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "dependency_lock_sha256": _sha256(Path("requirements-lock.txt")),
        },
        "seeds": _seeds(),
        "timing": {
            "started": started,
            "finished": finished,
            "receipt_written": datetime.now(UTC).isoformat(),
        },
        "artifacts": {
            name: _sha256(processed / name) for name in BUILT_ARTIFACTS
        },
        "byte_reproducible_artifacts": list(BYTE_REPRODUCIBLE),
        "notes": [
            (
                "Artifacts listed under byte_reproducible_artifacts rebuild to "
                "identical bytes from this commit and these seeds."
            ),
            (
                "ranking_model.skops is not byte-reproducible: skops writes "
                "bytes that differ on every save. Retraining on identical input "
                "yields identical coefficients and intercept, verified to zero "
                "difference, but a different file hash. Treat its hash as file "
                "integrity, not as evidence of a model change."
            ),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--script", default="rebuild.sh")
    parser.add_argument("--started", default=None)
    parser.add_argument("--finished", default=None)
    args = parser.parse_args()

    receipt = build_receipt(Path(args.script), args.started, args.finished)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    missing = [name for name, value in receipt["artifacts"].items() if value is None]
    print(json.dumps(receipt, indent=2))
    print(f"wrote {out}")
    if missing:
        print(f"WARNING: no such artifact: {missing}")
    if not receipt["build_commit"]["working_tree_clean"]:
        print(
            "WARNING: the tree was not clean, so this receipt does not "
            "establish that its commit produced these artifacts"
        )


if __name__ == "__main__":
    main()
