import json

import pytest

from recommender.retrieval.bundle import (
    BUNDLE_SCHEMA_VERSION,
    BundleError,
    build_manifest,
    file_sha256,
    load_manifest,
    validate_bundle,
    write_manifest,
)


def _artifacts(tmp_path, model=b"model-v1", content=b"content-v1", catalog=b"catalog-v1"):
    paths = {}
    for name, payload in (
        ("model", model), ("content", content), ("catalog", catalog),
    ):
        path = tmp_path / f"{name}.bin"
        path.write_bytes(payload)
        paths[name] = path
    return paths


def _publish(tmp_path, paths, catalog_items=100):
    manifest = build_manifest(
        retrieval_model_path=paths["model"],
        content_artifact_path=paths["content"],
        catalog_path=paths["catalog"],
        content_dim=64,
        embedding_dim=32,
        catalog_items=catalog_items,
        built_at="2026-08-25T00:00:00+00:00",
    )
    return write_manifest(manifest, path=tmp_path / "serving_bundle.json")


def test_a_bundle_published_together_validates(tmp_path):
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    validated = validate_bundle(
        paths["model"], paths["content"], paths["catalog"],
        catalog_items=100, path=manifest_path,
    )

    assert validated is not None
    assert validated.schema_version == BUNDLE_SCHEMA_VERSION


def test_a_content_artifact_from_a_different_training_run_is_refused(tmp_path):
    """The failure this bundle exists to prevent: a new content matrix
    beside an old model. The model would interpret every article's
    coordinates in a basis it was never trained on -- shapes still match,
    nothing raises, and the recommendations are quietly wrong.
    """
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    paths["content"].write_bytes(b"content-v2-from-a-later-run")

    with pytest.raises(BundleError, match="content artifact hash"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=manifest_path,
        )


def test_a_retrieval_model_from_a_different_run_is_refused(tmp_path):
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    paths["model"].write_bytes(b"model-v2")

    with pytest.raises(BundleError, match="retrieval model hash"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=manifest_path,
        )


def test_a_changed_catalog_is_refused(tmp_path):
    """This project serves a fixed catalog. Adding an article requires
    retraining and publishing a new bundle, so a changed catalog beside
    an unchanged model is a mismatch rather than an incremental update.
    """
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    paths["catalog"].write_bytes(b"catalog-with-a-new-article")

    with pytest.raises(BundleError, match="catalog hash"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=manifest_path,
        )


def test_a_catalog_with_a_different_article_count_is_refused(tmp_path):
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    with pytest.raises(BundleError, match="catalog has 101 articles"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=101, path=manifest_path,
        )


def test_a_missing_artifact_is_refused(tmp_path):
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    paths["content"].unlink()

    with pytest.raises(BundleError, match="content artifact is missing"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=manifest_path,
        )


def test_partial_training_failure_leaves_the_previous_bundle_intact(tmp_path):
    """Simulates training writing a new content matrix and then failing
    before it publishes a bundle.

    The previous manifest still describes the previous pair, so serving
    refuses the mismatched set rather than loading the new matrix against
    the old model. That refusal is the desired outcome: the alternative
    is silent, plausible-looking nonsense.
    """
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Training gets as far as the content matrix, then dies.
    paths["content"].write_bytes(b"content-v2-half-written-run")

    with pytest.raises(BundleError):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=manifest_path,
        )

    # The manifest was not touched by the failed run.
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original


def test_a_clean_clone_with_no_artifacts_and_no_manifest_is_accepted(tmp_path):
    """Nothing present, nothing to disagree about. A fresh clone has no
    artifacts at all and must still start.
    """
    assert validate_bundle(
        tmp_path / "model.bin", tmp_path / "content.bin", tmp_path / "catalog.bin",
        catalog_items=100, path=tmp_path / "absent.json",
    ) is None


def test_artifacts_without_a_manifest_are_rejected(tmp_path):
    """This test previously asserted the opposite, and in doing so
    encoded the gap it should have caught.

    A model, content matrix and catalog sitting there with no manifest is
    precisely what a partially failed training run leaves behind. Under
    the old rule, any incoherent artifact set could skip the entire
    bundle check simply by having no manifest -- so the check existed and
    could always be bypassed by the one failure mode it was written for.
    """
    paths = _artifacts(tmp_path)

    with pytest.raises(BundleError, match="no bundle manifest"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=tmp_path / "absent.json",
        )


def test_a_caller_may_opt_out_of_requiring_a_manifest(tmp_path):
    """The escape hatch is explicit and per-call, so tolerating a
    pre-manifest artifact set is a visible decision at the call site
    rather than the silent default. The serving path does not use it.
    """
    paths = _artifacts(tmp_path)

    assert validate_bundle(
        paths["model"], paths["content"], paths["catalog"],
        catalog_items=100, path=tmp_path / "absent.json", require_manifest=False,
    ) is None


def test_an_unreadable_manifest_raises_rather_than_being_ignored(tmp_path):
    paths = _artifacts(tmp_path)
    broken = tmp_path / "serving_bundle.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(BundleError, match="unreadable"):
        validate_bundle(
            paths["model"], paths["content"], paths["catalog"],
            catalog_items=100, path=broken,
        )


def test_manifest_write_is_atomic_and_leaves_no_temporary_files(tmp_path):
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)

    assert manifest_path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert load_manifest(manifest_path) is not None


def test_file_sha256_matches_the_recorded_hash(tmp_path):
    paths = _artifacts(tmp_path)
    manifest_path = _publish(tmp_path, paths)
    manifest = load_manifest(manifest_path)

    assert manifest.retrieval_model_sha256 == file_sha256(paths["model"])


def test_the_written_manifest_is_readable_by_other_users(tmp_path):
    """Regression test for a container-only failure.

    `tempfile.mkstemp` creates 0600 owned by the build user. Every other
    artifact beside the manifest is written under the normal umask and is
    world-readable, so the manifest alone arrived unreadable to a
    different user -- and the API died with PermissionError on this one
    file while every model and parquet next to it loaded fine.

    Skipped on Windows, where POSIX mode bits are not meaningfully
    enforced; the deployment that cares is a Linux container.
    """
    import os
    import stat
    import sys

    if sys.platform == "win32":
        pytest.skip("POSIX permission bits are not enforced on Windows")

    paths = _artifacts(tmp_path)
    manifest_path = tmp_path / "serving_bundle.json"
    write_manifest(
        build_manifest(
            retrieval_model_path=paths["model"],
            content_artifact_path=paths["content"],
            catalog_path=paths["catalog"],
            content_dim=64,
            embedding_dim=32,
            catalog_items=100,
            built_at="2026-08-26T00:00:00+00:00",
        ),
        path=manifest_path,
    )

    mode = stat.S_IMODE(os.stat(manifest_path).st_mode)

    assert mode & stat.S_IRGRP, f"manifest is not group-readable (mode {mode:o})"
    assert mode & stat.S_IROTH, f"manifest is not world-readable (mode {mode:o})"
