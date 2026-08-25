import copy

import pytest

from recommender.monitoring.artifact_manifest import (
    MISSING,
    _file_fingerprint,
    build_serving_artifact_manifest,
    compute_serving_version,
)

BASE_MANIFEST = {
    "retrieval_model_sha256_prefix": "aaaaaaaaaaaa",
    "ranking_model_sha256_prefix": "bbbbbbbbbbbb",
    "catalog_sha256_prefix": "cccccccccccc",
    "item_content_sha256_prefix": "dddddddddddd",
    "ranking_feature_schema": ["retrieval_score", "category_match", "content_similarity"],
    "embedding_dim": 32,
    "content_dim": 64,
    "content_transform_config": {
        "max_tfidf_features": 20000,
        "svd_seed": 42,
        "max_history": 20,
    },
    "retrieval_config": {"multiplier": 5, "min_candidates": 1000, "top_k": 10},
    "reranking_config": {
        "diversity_max_per_category": 3,
        "near_duplicate_threshold": 0.5,
        "freshness_threshold_days": 0.5,
        "freshness_min_fresh_in_slate": 2,
    },
    "explanation_model_name": "google/flan-t5-small",
    "explanation_model_revision": "0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab",
    "dependency_lock_sha256_prefix": "eeeeeeeeeeee",
    "serving_code_commit": "0123456789abcdef0123456789abcdef01234567",
}


def _mutate(path: tuple, value):
    """Returns BASE_MANIFEST with one nested field replaced."""
    mutated = copy.deepcopy(BASE_MANIFEST)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return mutated


def test_file_fingerprint_is_deterministic(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"some real artifact bytes")

    assert _file_fingerprint(path) == _file_fingerprint(path)
    assert len(_file_fingerprint(path)) == 12


def test_file_fingerprint_changes_with_the_real_file_contents(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"version one")
    fingerprint_one = _file_fingerprint(path)

    path.write_bytes(b"version two")
    fingerprint_two = _file_fingerprint(path)

    assert fingerprint_one != fingerprint_two


def test_file_fingerprint_reports_a_missing_artifact_rather_than_raising(tmp_path):
    """A machine that has not built every artifact must still be able to
    describe its own deployment. "This input is absent" is itself a real
    fact that should change the serving version.
    """
    assert _file_fingerprint(tmp_path / "never-created.bin") == MISSING


def test_compute_serving_version_is_deterministic():
    assert compute_serving_version(BASE_MANIFEST) == compute_serving_version(BASE_MANIFEST)


def test_compute_serving_version_is_independent_of_dict_key_order():
    reordered = dict(reversed(list(BASE_MANIFEST.items())))

    assert compute_serving_version(BASE_MANIFEST) == compute_serving_version(reordered)


# Every behaviour-affecting input the manifest claims to cover. If
# changing one of these does not move the serving version, two genuinely
# different deployments would report the same identity -- which is the
# whole failure this manifest exists to prevent.
BEHAVIOUR_AFFECTING_FIELDS = [
    pytest.param(("retrieval_model_sha256_prefix",), "changed", id="retrieval-model"),
    pytest.param(("ranking_model_sha256_prefix",), "changed", id="ranking-model"),
    pytest.param(("catalog_sha256_prefix",), "changed", id="catalog"),
    pytest.param(("item_content_sha256_prefix",), "changed", id="content-artifact"),
    pytest.param(("ranking_feature_schema",), ["retrieval_score"], id="feature-schema"),
    pytest.param(("embedding_dim",), 64, id="embedding-dim"),
    pytest.param(("content_dim",), 128, id="content-dim"),
    pytest.param(("content_transform_config", "max_tfidf_features"), 5000, id="tfidf-features"),
    pytest.param(("content_transform_config", "svd_seed"), 7, id="svd-seed"),
    pytest.param(("content_transform_config", "max_history"), 50, id="max-history"),
    pytest.param(("retrieval_config", "multiplier"), 10, id="retrieval-multiplier"),
    pytest.param(("retrieval_config", "min_candidates"), 50, id="retrieval-depth"),
    pytest.param(("retrieval_config", "top_k"), 20, id="top-k"),
    pytest.param(("reranking_config", "diversity_max_per_category"), 5, id="diversity-cap"),
    pytest.param(("reranking_config", "near_duplicate_threshold"), 0.9, id="near-duplicate"),
    pytest.param(("reranking_config", "freshness_threshold_days"), 2.0, id="freshness-threshold"),
    pytest.param(("reranking_config", "freshness_min_fresh_in_slate"), 4, id="min-fresh"),
    pytest.param(("explanation_model_name",), "other/model", id="explanation-model"),
    pytest.param(("explanation_model_revision",), "another-sha", id="explanation-revision"),
    pytest.param(("dependency_lock_sha256_prefix",), "changed", id="dependency-lock"),
    pytest.param(("serving_code_commit",), "a-different-commit", id="serving-commit"),
]


@pytest.mark.parametrize(("field_path", "new_value"), BEHAVIOUR_AFFECTING_FIELDS)
def test_serving_version_changes_when_a_behaviour_affecting_input_changes(field_path, new_value):
    mutated = _mutate(field_path, new_value)

    assert mutated != BASE_MANIFEST, f"{field_path} was not actually mutated"
    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_manifest_covers_every_field_the_version_test_asserts_on():
    """Guards against the manifest gaining a field that nothing above
    exercises -- the way the previous single-artifact fingerprint went
    unnoticed.
    """
    manifest = build_serving_artifact_manifest()
    covered = {path[0] for path, _ in (p.values for p in BEHAVIOUR_AFFECTING_FIELDS)}

    assert set(manifest) == set(BASE_MANIFEST), (
        "the real manifest and the test fixture have diverged; update BASE_MANIFEST"
    )
    assert set(manifest) == covered, (
        f"manifest fields with no version-change test: {set(manifest) - covered}"
    )


def test_build_serving_artifact_manifest_returns_the_expected_shape():
    """Runs against whatever artifacts this machine actually has.

    Deliberately does not require the licensed dataset or trained
    models: fingerprints of absent artifacts report `absent`, so the
    manifest's shape and its version derivation are verifiable from a
    clean clone. What each fingerprint contains when the artifact *is*
    present is covered by the fingerprint tests above.
    """
    manifest = build_serving_artifact_manifest()

    for key in (
        "retrieval_model_sha256_prefix",
        "ranking_model_sha256_prefix",
        "catalog_sha256_prefix",
        "item_content_sha256_prefix",
        "dependency_lock_sha256_prefix",
    ):
        assert key in manifest
        assert manifest[key] == MISSING or len(manifest[key]) == 12, key

    assert isinstance(manifest["ranking_feature_schema"], list)
    assert "popularity" not in manifest["ranking_feature_schema"]  # excluded from the trained model
    assert isinstance(manifest["reranking_config"], dict)
    assert isinstance(manifest["retrieval_config"], dict)
    # Named for what it actually is: the explanation layer's local
    # text-generation model, not an embedding model.
    assert "explanation_model_name" in manifest
    assert "embedding_model_name" not in manifest

    assert len(compute_serving_version(manifest)) == 12


def test_manifest_contains_no_obvious_secret_material():
    """The manifest is exposed on /metrics, so it must carry only public
    artifact hashes, configuration constants and commit identifiers.
    """
    manifest = build_serving_artifact_manifest()
    flat = repr(manifest).lower()

    for forbidden in ("password", "secret", "token", "api_key", "apikey"):
        assert forbidden not in flat
