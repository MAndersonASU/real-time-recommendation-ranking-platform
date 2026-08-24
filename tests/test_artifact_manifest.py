import copy

from recommender.monitoring.artifact_manifest import (
    _file_fingerprint,
    build_serving_artifact_manifest,
    compute_serving_version,
)

BASE_MANIFEST = {
    "retrieval_model_sha256_prefix": "aaaaaaaaaaaa",
    "ranking_model_sha256_prefix": "bbbbbbbbbbbb",
    "ranking_feature_schema": ["retrieval_score", "category_match", "content_similarity"],
    "catalog_sha256_prefix": "cccccccccccc",
    "embedding_model_name": "google/flan-t5-small",
    "embedding_model_revision": "0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab",
    "reranking_config": {
        "diversity_max_per_category": 3,
        "freshness_threshold_days": 0.5,
        "freshness_min_fresh_in_slate": 2,
    },
}


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


def test_compute_serving_version_is_deterministic():
    assert compute_serving_version(BASE_MANIFEST) == compute_serving_version(BASE_MANIFEST)


def test_compute_serving_version_is_independent_of_dict_key_order():
    reordered = dict(reversed(list(BASE_MANIFEST.items())))

    assert compute_serving_version(BASE_MANIFEST) == compute_serving_version(reordered)


def test_version_changes_when_retrieval_model_fingerprint_changes():
    """Regression test for a real gap, found by a follow-up audit: the
    prior version identifier fingerprinted only the retrieval model
    file, so changing any *other* serving-critical artifact silently
    left the reported version unchanged. Each test below proves the new,
    manifest-derived version actually moves for the artifact it names.
    """
    mutated = copy.deepcopy(BASE_MANIFEST)
    mutated["retrieval_model_sha256_prefix"] = "different_fp"

    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_version_changes_when_ranking_model_fingerprint_changes():
    mutated = copy.deepcopy(BASE_MANIFEST)
    mutated["ranking_model_sha256_prefix"] = "different_fp"

    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_version_changes_when_ranking_feature_schema_changes():
    mutated = copy.deepcopy(BASE_MANIFEST)
    mutated["ranking_feature_schema"] = ["retrieval_score", "category_match"]  # dropped a feature

    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_version_changes_when_catalog_fingerprint_changes():
    mutated = copy.deepcopy(BASE_MANIFEST)
    mutated["catalog_sha256_prefix"] = "different_fp"

    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_version_changes_when_embedding_model_revision_changes():
    mutated = copy.deepcopy(BASE_MANIFEST)
    mutated["embedding_model_revision"] = "a-different-commit-sha"

    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_version_changes_when_reranking_config_changes():
    mutated = copy.deepcopy(BASE_MANIFEST)
    mutated["reranking_config"]["diversity_max_per_category"] = 5

    assert compute_serving_version(mutated) != compute_serving_version(BASE_MANIFEST)


def test_build_serving_artifact_manifest_returns_the_real_expected_shape():
    """Integration-style check against the real, currently-trained
    project artifacts on disk (not synthetic fixtures) -- confirms every
    documented manifest field is really present and well-formed.
    """
    manifest = build_serving_artifact_manifest()

    for key in (
        "retrieval_model_sha256_prefix",
        "ranking_model_sha256_prefix",
        "ranking_feature_schema",
        "catalog_sha256_prefix",
        "embedding_model_name",
        "embedding_model_revision",
        "reranking_config",
    ):
        assert key in manifest

    assert len(manifest["retrieval_model_sha256_prefix"]) == 12
    assert len(manifest["ranking_model_sha256_prefix"]) == 12
    assert len(manifest["catalog_sha256_prefix"]) == 12
    assert isinstance(manifest["ranking_feature_schema"], list)
    assert "popularity" not in manifest["ranking_feature_schema"]  # excluded from the trained model
    assert isinstance(manifest["reranking_config"], dict)

    version = compute_serving_version(manifest)
    assert len(version) == 12
