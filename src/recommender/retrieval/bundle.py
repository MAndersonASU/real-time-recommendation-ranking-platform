"""Binds the serving artifacts into one bundle that is written and
validated together.

The retrieval model and the content matrix are two files that must agree
on one thing: the fitted basis the model was trained against. Nothing
enforced that. If training wrote a new content matrix and then failed
before writing the model, serving would load a *new* matrix with an
*old* model and interpret every article's coordinates in a basis the
model had never seen. Shapes still match, no exception is raised, and
the recommendations are quietly wrong.

The bundle records what each artifact was when they were built together
and refuses to load a set that no longer agrees. Artifacts are staged in
a temporary directory and moved into place only once all of them are
written, so a failed run leaves the previous good bundle untouched
rather than a half-updated mix.

Scope: this project serves a fixed catalog. The fitted TF-IDF and SVD
transformers are deliberately not persisted, because nothing here
projects a genuinely new article into the trained basis. Onboarding a
new article therefore requires retraining and publishing a new bundle,
which the catalog check below makes explicit rather than leaving as an
unnoticed mismatch.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from recommender.paths import mind_small_path

BUNDLE_MANIFEST_PATH = mind_small_path("serving_bundle.json")

BUNDLE_SCHEMA_VERSION = 1


class BundleError(RuntimeError):
    """The serving artifacts do not form a coherent bundle.

    Fatal by design: continuing would mean serving a model against a
    basis it was not trained on, which produces plausible-looking
    nonsense rather than a detectable failure.
    """


@dataclass(frozen=True)
class BundleManifest:
    schema_version: int
    retrieval_model_sha256: str
    content_artifact_sha256: str
    catalog_sha256: str
    content_dim: int
    embedding_dim: int
    catalog_items: int
    built_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_manifest(
    retrieval_model_path: Path,
    content_artifact_path: Path,
    catalog_path: Path,
    content_dim: int,
    embedding_dim: int,
    catalog_items: int,
    built_at: str,
) -> BundleManifest:
    return BundleManifest(
        schema_version=BUNDLE_SCHEMA_VERSION,
        retrieval_model_sha256=file_sha256(retrieval_model_path),
        content_artifact_sha256=file_sha256(content_artifact_path),
        catalog_sha256=file_sha256(catalog_path),
        content_dim=content_dim,
        embedding_dim=embedding_dim,
        catalog_items=catalog_items,
        built_at=built_at,
    )


def write_manifest(manifest: BundleManifest, path: Path = BUNDLE_MANIFEST_PATH) -> Path:
    """Writes the manifest atomically.

    A partially written manifest would be worse than none: it would
    describe a bundle that does not exist while looking authoritative.
    Written to a temporary file in the same directory and renamed, since
    a same-filesystem rename is atomic.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(manifest.to_json())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path


def load_manifest(path: Path = BUNDLE_MANIFEST_PATH) -> BundleManifest | None:
    """Returns None when no bundle manifest exists.

    Absence is tolerated so an installation predating the bundle, or a
    clean clone with no artifacts at all, still starts -- it simply gets
    no cross-artifact guarantee. A manifest that exists but disagrees
    with the artifacts is a different matter and raises.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BundleManifest(**data)
    except (ValueError, TypeError) as exc:
        raise BundleError(f"serving bundle manifest at {path} is unreadable: {exc}") from exc


def validate_bundle(
    retrieval_model_path: Path,
    content_artifact_path: Path,
    catalog_path: Path,
    catalog_items: int,
    path: Path = BUNDLE_MANIFEST_PATH,
) -> BundleManifest | None:
    """Checks that the artifacts on disk are the ones recorded together.

    Returns the manifest when it validates, or None when no manifest
    exists. Raises when a manifest exists and any artifact has changed
    independently of the others -- the case that would otherwise serve a
    model against a foreign basis.
    """
    manifest = load_manifest(path)
    if manifest is None:
        return None

    mismatches = []
    for label, artifact_path, expected in (
        ("retrieval model", retrieval_model_path, manifest.retrieval_model_sha256),
        ("content artifact", content_artifact_path, manifest.content_artifact_sha256),
        ("catalog", catalog_path, manifest.catalog_sha256),
    ):
        artifact_path = Path(artifact_path)
        if not artifact_path.exists():
            mismatches.append(f"{label} is missing at {artifact_path}")
            continue
        actual = file_sha256(artifact_path)
        if actual != expected:
            mismatches.append(
                f"{label} hash {actual[:12]} does not match the bundle's {expected[:12]}"
            )

    if catalog_items != manifest.catalog_items:
        mismatches.append(
            f"catalog has {catalog_items} articles but the bundle was built from "
            f"{manifest.catalog_items}"
        )

    if mismatches:
        raise BundleError(
            "serving artifacts do not form a coherent bundle: "
            + "; ".join(mismatches)
            + ". Retrain to publish a matching bundle -- this project serves a fixed "
            "catalog, so adding or changing articles requires a new bundle rather "
            "than an in-place update."
        )
    return manifest
