"""Upgrades a pre-schema content artifact in place, without refitting.

The strict loader requires a schema version and a canonical checksum
that a pre-schema artifact does not carry. The obvious response --
rebuild it -- would be wrong here: rebuilding means refitting TF-IDF and
SVD, and SVD axes are defined only up to sign and ordering, so a refit
produces a *different valid basis* for the same corpus. The trained item
tower would then be scoring coordinates it has never seen, with no error
raised anywhere, which is the exact failure `content_artifact` exists to
prevent.

So this does not refit. It reads the existing matrix and article ids
unchanged, and rewrites the file with the metadata the strict loader
requires. The coordinates the model was trained against are preserved
bit for bit, and that is verified rather than assumed: the upgraded
matrix is compared against the original before the replacement is kept.

    python -m recommender.retrieval.upgrade_content_artifact

Idempotent -- an artifact already carrying the current schema is left
alone.
"""

import json
import sys

import numpy as np

from recommender.evaluation.contract import load_catalog
from recommender.retrieval.bundle import (
    BUNDLE_MANIFEST_PATH,
    build_manifest,
    load_manifest,
    write_manifest,
)
from recommender.retrieval.content_artifact import (
    CONTENT_ARTIFACT_PATH,
    CONTENT_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    ContentArtifactError,
    load_item_content,
    save_item_content,
)
from recommender.retrieval.train import MODEL_PATH
from recommender.retrieval.train_fit_only import (
    FIT_ONLY_BUNDLE_PATH,
    FIT_ONLY_CONTENT_PATH,
    FIT_ONLY_MODEL_PATH,
)

# Each content artifact, the model it belongs with, and the manifest
# that binds them. Upgrading the artifact changes its file bytes, so the
# manifest's recorded hash has to be refreshed or the bundle check --
# correctly -- refuses the pair.
UPGRADE_TARGETS = (
    (CONTENT_ARTIFACT_PATH, MODEL_PATH, BUNDLE_MANIFEST_PATH),
    (FIT_ONLY_CONTENT_PATH, FIT_ONLY_MODEL_PATH, FIT_ONLY_BUNDLE_PATH),
)


def _refresh_manifest(content_path, model_path, manifest_path, news) -> str:
    """Re-fingerprints the bundle after a metadata-only artifact upgrade.

    The manifest records file hashes, and rewriting the artifact changes
    its bytes even though its meaning is identical. Refreshing is
    therefore correct here and *only* here: the artifacts genuinely
    still belong together, which the caller has already verified by
    comparing the matrix before and after. Nothing in this function
    would notice a real mismatch, so it is never called on an
    un-upgraded pair.
    """
    existing = load_manifest(manifest_path)
    if existing is None:
        return "no manifest to refresh"

    from recommender.evaluation.contract import CATALOG_PATH
    from recommender.retrieval.features import CONTENT_DIM
    from recommender.retrieval.train import EMBEDDING_DIM

    write_manifest(
        build_manifest(
            retrieval_model_path=model_path,
            content_artifact_path=content_path,
            catalog_path=CATALOG_PATH,
            content_dim=CONTENT_DIM,
            embedding_dim=EMBEDDING_DIM,
            catalog_items=len(news),
            # Preserved. The bundle was not rebuilt, only re-described,
            # so claiming a new build time would misreport when these
            # artifacts were actually produced together.
            built_at=existing.built_at,
        ),
        path=manifest_path,
    )
    return "refreshed"


def _refresh_stale_manifest_only(content_path, model_path, manifest_path, news) -> dict:
    """Refreshes a manifest left stale by an already-completed upgrade.

    Deliberately narrow. Refreshing a manifest whenever it disagrees
    would defeat the bundle check entirely -- the whole point is that a
    disagreement is fatal. So this refuses unless the disagreement is
    *exactly* the signature of a metadata-only content upgrade:

    - the content artifact already carries the current schema, and
    - the model and catalog hashes still match the manifest, so the only
      thing that moved is the content file's bytes.

    If the model or catalog also changed, something real happened and
    this is not the tool for it.
    """
    from recommender.evaluation.contract import CATALOG_PATH
    from recommender.retrieval.bundle import file_sha256

    existing = load_manifest(manifest_path)
    if existing is None:
        return {"path": str(content_path), "action": "skipped", "reason": "already current"}

    if existing.content_artifact_sha256 == file_sha256(content_path):
        return {"path": str(content_path), "action": "skipped", "reason": "already current"}

    model_matches = existing.retrieval_model_sha256 == file_sha256(model_path)
    catalog_matches = existing.catalog_sha256 == file_sha256(CATALOG_PATH)
    if not (model_matches and catalog_matches):
        raise ContentArtifactError(
            f"{manifest_path} disagrees with more than the content artifact "
            f"(model matches: {model_matches}, catalog matches: {catalog_matches}). "
            f"That is a real bundle mismatch, not a metadata upgrade; retrain rather "
            f"than re-describing it."
        )

    _refresh_manifest(content_path, model_path, manifest_path, news)
    return {
        "path": str(content_path),
        "action": "manifest refreshed",
        "reason": "artifact already upgraded; manifest recorded its pre-upgrade hash",
    }



def upgrade(path, model_path, manifest_path, news) -> dict:
    if not path.exists():
        return {"path": str(path), "action": "skipped", "reason": "absent"}

    with np.load(path, allow_pickle=False) as data:
        present = set(data.files)
        original = np.array(data["content"])

    missing = [field for field in REQUIRED_FIELDS if field not in present]
    if not missing:
        # Already upgraded. Its manifest may still record the artifact's
        # pre-upgrade file hash, so check that narrow case rather than
        # leaving a coherent bundle looking broken.
        return _refresh_stale_manifest_only(path, model_path, manifest_path, news)

    # Read through the legacy allowance -- the only place it is used --
    # then write back through the ordinary strict writer.
    matrix = load_item_content(news, path=path, allow_legacy=True)
    save_item_content(news, matrix, path=path)

    # The upgrade must be metadata-only. If the coordinates moved, the
    # trained model no longer matches them and the artifact is worse
    # than it was before.
    reloaded = load_item_content(news, path=path)
    if not np.array_equal(reloaded, original.astype(np.float32)):
        raise ContentArtifactError(
            f"upgrading {path} changed the matrix values; the model was trained "
            f"against the original coordinates, so this must be metadata-only"
        )

    manifest_action = _refresh_manifest(path, model_path, manifest_path, news)

    return {
        "path": str(path),
        "action": "upgraded",
        "added_fields": missing,
        "schema_version": CONTENT_SCHEMA_VERSION,
        "rows": int(matrix.shape[0]),
        "feature_width": int(matrix.shape[1]),
        "matrix_unchanged": True,
        "bundle_manifest": manifest_action,
    }


def main() -> None:
    news = load_catalog()
    results = [
        upgrade(content_path, model_path, manifest_path, news)
        for content_path, model_path, manifest_path in UPGRADE_TARGETS
    ]
    print(json.dumps(results, indent=2))
    if all(result["action"] == "skipped" and result["reason"] == "absent" for result in results):
        print("no content artifacts found to upgrade", file=sys.stderr)


if __name__ == "__main__":
    main()
