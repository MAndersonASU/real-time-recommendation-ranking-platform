"""The migration tool must not be able to bless a foreign artifact.

`upgrade_content_artifact` publishes a bundle manifest, which means it
can defeat the check that manifest exists to enforce. An earlier version
did: it refreshed a stale manifest whenever the model and catalog hashes
still matched -- precisely the files that stay unchanged when only the
content matrix is swapped.

Reproduced at the time: `validate_bundle` correctly refused a foreign
matrix, the migration tool refreshed the manifest, and `validate_bundle`
then accepted it. A content matrix from an entirely different fitted
basis would have been served, which is the exact failure
ARTIFACT-BUNDLE-06 was written to prevent.

These tests pin the properties that closed it.
"""

import numpy as np
import pandas as pd
import pytest

from recommender.retrieval.bundle import (
    BundleError,
    build_manifest,
    validate_bundle,
    write_manifest,
)
from recommender.retrieval.content_artifact import (
    CONTENT_DIM,
    _legacy_matrix_checksum,
    load_item_content,
)
from recommender.retrieval.upgrade_content_artifact import (
    MigrationError,
    semantic_digest,
    upgrade,
)

NEWS = pd.DataFrame(
    {
        "news_id": [f"N{i}" for i in range(6)],
        "category": ["news"] * 6,
        "subcategory": ["politics"] * 6,
        "title": [f"title {i}" for i in range(6)],
        "abstract": [f"abstract {i}" for i in range(6)],
    }
)


def _write_legacy(path, content, news_ids):
    """A pre-schema artifact: no schema_version, old bytes-only digest."""
    np.savez(
        path,
        content=content,
        news_ids=news_ids,
        feature_width=np.int64(CONTENT_DIM),
        content_sha256=np.array(_legacy_matrix_checksum(content)),
    )


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A coherent legacy bundle: model, catalog, artifact, manifest."""
    import recommender.retrieval.upgrade_content_artifact as module

    model = tmp_path / "model.pt"
    model.write_bytes(b"trained-model-bytes")
    catalog = tmp_path / "catalog.parquet"
    NEWS.to_parquet(catalog)
    content = tmp_path / "content.npz"
    manifest = tmp_path / "bundle.json"

    original = np.arange(6 * CONTENT_DIM, dtype=np.float32).reshape(6, CONTENT_DIM)
    news_ids = NEWS["news_id"].to_numpy().astype(str)
    _write_legacy(content, original, news_ids)

    write_manifest(
        build_manifest(
            retrieval_model_path=model,
            content_artifact_path=content,
            catalog_path=catalog,
            content_dim=CONTENT_DIM,
            embedding_dim=32,
            catalog_items=len(NEWS),
            built_at="2026-01-01T00:00:00+00:00",
        ),
        path=manifest,
    )
    monkeypatch.setattr(module, "CATALOG_PATH", catalog)
    return {
        "model": model,
        "catalog": catalog,
        "content": content,
        "manifest": manifest,
        "original": original,
        "news_ids": news_ids,
    }


def test_a_metadata_only_migration_preserves_the_matrix_and_ordering(bundle):
    result = upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)

    assert result["action"] == "upgraded"
    assert result["semantic_digest_before"] == result["semantic_digest_after"]
    assert result["matrix_unchanged"] is True

    loaded = load_item_content(NEWS, path=bundle["content"])
    assert np.array_equal(loaded, bundle["original"])

    with np.load(bundle["content"], allow_pickle=False) as data:
        assert np.array_equal(np.array(data["news_ids"]).astype(str), bundle["news_ids"])
        assert int(data["schema_version"]) == 1

    assert validate_bundle(
        bundle["model"], bundle["content"], bundle["catalog"],
        catalog_items=len(NEWS), path=bundle["manifest"],
    ) is not None


def test_a_foreign_matrix_is_refused_even_though_model_and_catalog_match(bundle):
    """The reproduced vulnerability, in the exact shape it was found.

    Only the content matrix is replaced. The model and catalog hashes --
    the ones the old guard checked -- still match perfectly, which is
    what made that guard useless: they are unchanged by construction in
    this attack.
    """
    foreign = np.full((6, CONTENT_DIM), 7.5, dtype=np.float32)
    _write_legacy(bundle["content"], foreign, bundle["news_ids"])

    with pytest.raises(MigrationError, match="does not validate"):
        upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)

    # And the bundle must still refuse it afterwards -- the failed
    # migration must not have published anything.
    with pytest.raises(BundleError):
        validate_bundle(
            bundle["model"], bundle["content"], bundle["catalog"],
            catalog_items=len(NEWS), path=bundle["manifest"],
        )


def test_reordered_ids_are_refused(bundle):
    """The matrix bytes are untouched; only the ordering moves. Every
    article's content vector would belong to a different article.
    """
    _write_legacy(bundle["content"], bundle["original"], bundle["news_ids"][::-1].copy())

    with pytest.raises(MigrationError):
        upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)


def test_a_bad_internal_checksum_is_refused(bundle):
    np.savez(
        bundle["content"],
        content=bundle["original"],
        news_ids=bundle["news_ids"],
        feature_width=np.int64(CONTENT_DIM),
        content_sha256=np.array("0" * 64),
    )

    with pytest.raises((MigrationError, Exception)):
        upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)


def test_a_missing_manifest_is_refused_rather_than_created(bundle):
    """Without a manifest there is nothing saying what this artifact is
    supposed to be, so a migration cannot verify it preserved anything.
    Issuing a fresh one would assert coherence nobody checked.
    """
    bundle["manifest"].unlink()

    with pytest.raises(MigrationError, match="no bundle manifest"):
        upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)

    assert not bundle["manifest"].exists(), "a refused migration must not publish"


def test_an_interrupted_migration_restores_the_original(bundle, monkeypatch):
    """Failure partway must leave the original bundle intact, not a
    half-updated mix.
    """
    import recommender.retrieval.upgrade_content_artifact as module

    before_bytes = bundle["content"].read_bytes()
    before_manifest = bundle["manifest"].read_bytes()

    def explode(*_args, **_kwargs):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(module, "write_manifest", explode)

    with pytest.raises(RuntimeError, match="interrupted"):
        upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)

    assert bundle["content"].read_bytes() == before_bytes
    assert bundle["manifest"].read_bytes() == before_manifest
    assert not list(bundle["content"].parent.glob("*.migrating.npz")), (
        "the temporary artifact must not be left behind"
    )


def test_an_already_current_artifact_is_left_alone_manifest_included(bundle):
    """Idempotent, and deliberately inert. A stale manifest on an
    already-current artifact is *not* refreshed: this tool cannot tell a
    stale manifest from a swapped artifact, and guessing is what created
    the vulnerability.
    """
    upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)
    manifest_after_first = bundle["manifest"].read_bytes()

    result = upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)

    assert result["action"] == "skipped"
    assert result["reason"] == "already current"
    assert bundle["manifest"].read_bytes() == manifest_after_first


def test_the_semantic_digest_ignores_packaging_but_not_meaning():
    """It must be blind to how the artifact is stored and sensitive to
    what it contains, or comparing it before and after proves nothing.
    """
    content = np.zeros((3, 4), dtype=np.float32)
    ids = np.array(["a", "b", "c"])
    baseline = semantic_digest(content, ids)

    assert semantic_digest(content.copy(), ids.copy()) == baseline

    changed = content.copy()
    changed[0, 0] = 1.0
    assert semantic_digest(changed, ids) != baseline
    assert semantic_digest(content, ids[::-1].copy()) != baseline
    assert semantic_digest(content.reshape(4, 3), ids) != baseline


def test_the_receipt_names_the_superseded_manifest_not_the_new_one(bundle):
    """The receipt must identify what the migration replaced.

    An earlier version hashed the manifest file *after* publishing, so
    `original_manifest_sha256` held the digest of the replacement -- the
    artifact the migration created, not the one it superseded. A receipt
    built that way cannot be checked against the prior state, which is
    the only thing it is for.
    """
    import hashlib

    manifest_before = hashlib.sha256(bundle["manifest"].read_bytes()).hexdigest()

    result = upgrade(bundle["content"], bundle["model"], bundle["manifest"], NEWS)

    manifest_after = hashlib.sha256(bundle["manifest"].read_bytes()).hexdigest()

    assert result["original_manifest_sha256"] == manifest_before
    assert result["published_manifest_sha256"] == manifest_after
    assert manifest_before != manifest_after, (
        "the migration must have republished the manifest, or this test proves nothing"
    )
