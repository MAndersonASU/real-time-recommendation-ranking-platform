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
unchanged and rewrites the file with the metadata the strict loader
requires, preserving the coordinates the model was trained against bit
for bit.

**This tool publishes a new bundle manifest, so it can defeat the very
check that manifest exists to enforce.** An earlier version did exactly
that. It refreshed a stale manifest whenever the model and catalog
hashes still matched -- which are precisely the files that stay
unchanged when only the content matrix is swapped. A content matrix from
an entirely foreign basis could be dropped in, handed a fresh manifest,
and would then pass serving validation. Reproduced directly: the bundle
correctly refused the foreign matrix, and the migration tool blessed it.

Every step below exists because of that. The rule now is that a manifest
is only ever published for content this run has itself verified to be
semantically identical to what the original bundle covered:

1. Validate the complete original bundle before touching anything.
2. Keep the original bytes for rollback.
3. Write the upgrade to a temporary path, never over the original.
4. Strict-load the temporary artifact.
5. Require ordered ids and matrix values to be bit-identical.
6. Build the manifest against that verified artifact.
7. Publish, restoring the original on any failure.

There is no path that refreshes a manifest without performing a verified
migration in the same run.

    python -m recommender.retrieval.upgrade_content_artifact

Idempotent -- an artifact already carrying the current schema is left
alone, manifest included.
"""

import hashlib
import json
import sys

import numpy as np

from recommender.evaluation.contract import CATALOG_PATH, load_catalog
from recommender.retrieval.bundle import (
    BUNDLE_MANIFEST_PATH,
    BundleError,
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
from recommender.retrieval.features import CONTENT_DIM
from recommender.retrieval.train import EMBEDDING_DIM, MODEL_PATH
from recommender.retrieval.train_fit_only import (
    FIT_ONLY_BUNDLE_PATH,
    FIT_ONLY_CONTENT_PATH,
    FIT_ONLY_MODEL_PATH,
)

UPGRADE_TARGETS = (
    (CONTENT_ARTIFACT_PATH, MODEL_PATH, BUNDLE_MANIFEST_PATH),
    (FIT_ONLY_CONTENT_PATH, FIT_ONLY_MODEL_PATH, FIT_ONLY_BUNDLE_PATH),
)


class MigrationError(RuntimeError):
    """The migration could not be completed safely and was rolled back."""


def semantic_digest(content: np.ndarray, news_ids: np.ndarray) -> str:
    """What the artifact *means*, independent of how it is stored.

    Ordered article ids plus matrix values, and nothing else -- not the
    schema version, not the file layout. That is the point: a
    metadata-only upgrade must leave this identical, so comparing it
    before and after is what proves the migration changed only the
    packaging.
    """
    digest = hashlib.sha256()
    digest.update(f"ids={len(news_ids)}\n".encode())
    for article_id in news_ids:
        digest.update(f"{len(str(article_id))}:{article_id}\n".encode())
    digest.update(f"shape={content.shape[0]}x{content.shape[1]}\n".encode())
    digest.update(np.ascontiguousarray(content, dtype=np.float32).tobytes())
    return digest.hexdigest()


def _read_payload(path):
    """Ordered ids and matrix, read without any validation.

    Used to capture the *original* state before migration, so it must
    not go through the strict loader -- the artifact being migrated is by
    definition one the strict loader rejects.
    """
    with np.load(path, allow_pickle=False) as data:
        return (
            np.array(data["content"]).astype(np.float32),
            np.array(data["news_ids"]).astype(str),
            set(data.files),
        )


def upgrade(content_path, model_path, manifest_path, news) -> dict:
    if not content_path.exists():
        return {"path": str(content_path), "action": "skipped", "reason": "absent"}

    original_bytes = content_path.read_bytes()
    original_content, original_ids, present = _read_payload(content_path)
    before = semantic_digest(original_content, original_ids)

    if not [field for field in REQUIRED_FIELDS if field not in present]:
        # Already current. Nothing is republished -- in particular, a
        # manifest that disagrees is left disagreeing, because this tool
        # has no way to tell a stale manifest from a swapped artifact.
        return {"path": str(content_path), "action": "skipped", "reason": "already current"}

    # 1. The original bundle must be coherent before anything moves. A
    #    manifest is a statement that these artifacts belong together; if
    #    that is already false, migrating produces a *new* manifest
    #    asserting it, which is how a foreign matrix gets blessed.
    original_manifest = load_manifest(manifest_path)
    if original_manifest is None:
        raise MigrationError(
            f"no bundle manifest at {manifest_path}. Without one there is nothing "
            f"establishing what this content artifact is supposed to be, so a "
            f"migration cannot verify it preserved anything. Retrain instead."
        )
    try:
        from recommender.retrieval.bundle import validate_bundle

        validate_bundle(
            model_path, content_path, CATALOG_PATH,
            catalog_items=len(news), path=manifest_path,
        )
    except BundleError as error:
        raise MigrationError(
            f"the existing bundle at {manifest_path} does not validate, so this "
            f"artifact is not the one the manifest covers: {error}. Migration would "
            f"issue a fresh manifest blessing whatever is on disk. Retrain instead."
        ) from error

    # 2-3. Write the upgrade beside the original, never over it.
    # Must still end in .npz: np.savez appends the extension when the
    # path lacks it, so "content.npz.migrating" would silently become
    # "content.npz.migrating.npz" and the verification step would look
    # for a file that was never written.
    temporary_path = content_path.with_name(f"{content_path.stem}.migrating.npz")
    try:
        save_item_content(news, original_content, path=temporary_path)

        # 4. Strict-load what was written -- the same path serving uses.
        migrated = load_item_content(news, path=temporary_path)
        _, migrated_ids, _ = _read_payload(temporary_path)

        # 5. Ordered ids and matrix values must be bit-identical.
        after = semantic_digest(migrated, migrated_ids)
        if after != before:
            raise MigrationError(
                f"migration changed what the artifact means (semantic digest "
                f"{before[:12]} -> {after[:12]}). The model was trained against the "
                f"original coordinates, so only the packaging may change."
            )
        if not np.array_equal(migrated_ids, original_ids):
            raise MigrationError("migration changed the article ordering")
        if not np.array_equal(migrated, original_content):
            raise MigrationError("migration changed the matrix values")

        # 6-7. Publish, restoring the original on any failure.
        temporary_path.replace(content_path)
        try:
            write_manifest(
                build_manifest(
                    retrieval_model_path=model_path,
                    content_artifact_path=content_path,
                    catalog_path=CATALOG_PATH,
                    content_dim=CONTENT_DIM,
                    embedding_dim=EMBEDDING_DIM,
                    catalog_items=len(news),
                    # Preserved: the bundle was re-described, not rebuilt.
                    built_at=original_manifest.built_at,
                ),
                path=manifest_path,
            )
        except BaseException:
            content_path.write_bytes(original_bytes)
            raise
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        if content_path.read_bytes() != original_bytes:
            content_path.write_bytes(original_bytes)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)

    return {
        "path": str(content_path),
        "action": "upgraded",
        "schema_version": CONTENT_SCHEMA_VERSION,
        "rows": int(migrated.shape[0]),
        "feature_width": int(migrated.shape[1]),
        # The migration receipt: identical before and after, computed in
        # this run, over the two things that define the artifact.
        "semantic_digest_before": before,
        "semantic_digest_after": after,
        "original_manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "matrix_unchanged": True,
    }


def main() -> None:
    news = load_catalog()
    results = []
    for content_path, model_path, manifest_path in UPGRADE_TARGETS:
        try:
            results.append(upgrade(content_path, model_path, manifest_path, news))
        except (MigrationError, ContentArtifactError) as error:
            results.append(
                {"path": str(content_path), "action": "refused", "reason": str(error)}
            )
    print(json.dumps(results, indent=2))
    if any(result["action"] == "refused" for result in results):
        raise SystemExit(1)
    if all(result.get("reason") == "absent" for result in results):
        print("no content artifacts found to upgrade", file=sys.stderr)


if __name__ == "__main__":
    main()
