import hashlib
import json
import os
import subprocess
from pathlib import Path

# Anchored to this project's own root so the commit lookup below cannot
# accidentally describe whatever repository the caller happened to be
# standing in.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

MISSING = "absent"


def _file_fingerprint(path: Path) -> str:
    """First 12 hex characters of the file's SHA-256, computed from the
    bytes actually on disk -- a genuine fingerprint of exactly which
    artifact is present, not a label that could drift from the file.

    A missing artifact reports `absent` rather than raising: the manifest
    has to be describable even on a machine that has not built every
    artifact, and "this input was not present" is itself a real fact
    about the deployment that should change the serving version.
    """
    if not path.exists():
        return MISSING
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _serving_code_commit() -> str:
    """The commit the serving code was built from. `GIT_COMMIT_SHA` is
    authoritative because a container image has no `.git` directory at
    all; repository discovery is the local-development fallback.
    """
    from_env = os.environ.get("GIT_COMMIT_SHA")
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_PROJECT_ROOT, capture_output=True, text=True, check=True, timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return MISSING


def _behaviour_split_fingerprints() -> dict:
    """Fingerprints of the behaviour splits that derived serving state is
    computed from.

    Hashes the split files themselves rather than the derived structures:
    the derivation is deterministic given the code (whose commit is
    already in the manifest), so the inputs plus the code identify the
    outputs. Hashing multi-hundred-megabyte in-memory frames on every
    manifest build would also be real startup cost for no extra
    information.
    """
    from recommender.evaluation.contract import SPLITS_DIR

    fingerprints = {}
    for split in ("train", "validation"):
        fingerprints[split] = _file_fingerprint(SPLITS_DIR / split / "behaviors.parquet")
    return fingerprints


def build_serving_artifact_manifest() -> dict:
    """Every persisted artifact and behaviour-affecting configuration
    value that determines what a live request is served.

    The organising rule: if changing it could change the items a user
    receives, or their order, it belongs here. That includes things that
    are not files -- retrieval depth, the near-duplicate threshold and
    the reranking caps all reshape a slate without any artifact changing
    on disk, so a manifest built only from file hashes would report an
    unchanged version across a real behavioural change.

    Two entries that are not obvious:

    - The Faiss index is not listed separately. `build_serving_context`
      never loads a saved index; it rebuilds one in memory from the
      retrieval model's embeddings and the catalog, so its identity is
      already implied by those two plus the content artifact.
    - The dependency lock digest is included because the numerical
      output of torch, scikit-learn and faiss is version-dependent. Two
      deployments with identical model files and different dependency
      sets are not guaranteed to rank identically.

    Nothing secret is included: every value is a public artifact hash, a
    configuration constant, or a commit identifier.
    """
    from recommender.evaluation.contract import CATALOG_PATH, TOP_K
    from recommender.explanation.generation import MODEL_NAME, MODEL_REVISION
    from recommender.ranking.train import MODEL_FEATURE_COLUMNS
    from recommender.ranking.train import MODEL_PATH as RANKING_MODEL_PATH
    from recommender.reranking.diversity import (
        DEFAULT_MAX_PER_CATEGORY,
        DEFAULT_NEAR_DUPLICATE_THRESHOLD,
    )
    from recommender.reranking.freshness import (
        DEFAULT_FRESH_THRESHOLD_DAYS,
        DEFAULT_MIN_FRESH_IN_SLATE,
    )
    from recommender.retrieval.content_artifact import (
        CONTENT_ARTIFACT_PATH,
        content_artifact_fingerprint,
    )
    from recommender.retrieval.features import (
        CONTENT_DIM,
        CONTENT_MAX_FEATURES,
        CONTENT_SEED,
        MAX_HISTORY,
    )
    from recommender.retrieval.train import EMBEDDING_DIM
    from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH
    from recommender.serving.pipeline import (
        MIN_RETRIEVAL_CANDIDATES,
        RETRIEVAL_MULTIPLIER,
    )

    lock_path = _PROJECT_ROOT / "requirements-lock.txt"

    return {
        # --- persisted artifacts ---
        "retrieval_model_sha256_prefix": _file_fingerprint(RETRIEVAL_MODEL_PATH),
        "ranking_model_sha256_prefix": _file_fingerprint(RANKING_MODEL_PATH),
        "catalog_sha256_prefix": _file_fingerprint(CATALOG_PATH),
        # The fitted article-content transformation. Refitting it can
        # produce a different SVD basis for the same corpus, so which
        # exact matrix is loaded is serving-critical
        # (recommender.retrieval.content_artifact).
        "item_content_sha256_prefix": content_artifact_fingerprint(CONTENT_ARTIFACT_PATH) or MISSING,
        # --- feature and model shape ---
        "ranking_feature_schema": list(MODEL_FEATURE_COLUMNS),
        "embedding_dim": EMBEDDING_DIM,
        "content_dim": CONTENT_DIM,
        "content_transform_config": {
            "max_tfidf_features": CONTENT_MAX_FEATURES,
            "svd_seed": CONTENT_SEED,
            "max_history": MAX_HISTORY,
        },
        # --- retrieval behaviour ---
        "retrieval_config": {
            "multiplier": RETRIEVAL_MULTIPLIER,
            "min_candidates": MIN_RETRIEVAL_CANDIDATES,
            "top_k": TOP_K,
        },
        # --- reranking behaviour ---
        "reranking_config": {
            "diversity_max_per_category": DEFAULT_MAX_PER_CATEGORY,
            "near_duplicate_threshold": DEFAULT_NEAR_DUPLICATE_THRESHOLD,
            "freshness_threshold_days": DEFAULT_FRESH_THRESHOLD_DAYS,
            "freshness_min_fresh_in_slate": DEFAULT_MIN_FRESH_IN_SLATE,
        },
        # --- explanation layer ---
        # Named for what it is. An earlier manifest called this the
        # "embedding model", which it is not: it is the local
        # text-generation model the explanation layer uses to rewrite an
        # already-made recommendation's wording
        # (recommender.explanation.generation).
        "explanation_model_name": MODEL_NAME,
        "explanation_model_revision": MODEL_REVISION,
        # --- environment ---
        "dependency_lock_sha256_prefix": _file_fingerprint(lock_path),
        "serving_code_commit": _serving_code_commit(),
        # --- behaviour splits and derived snapshots ---
        # Popularity, first-seen and durable features are all derived
        # from behaviour data at startup rather than read from a
        # single artifact file. Hashing only the model files left them
        # invisible: swapping the underlying split changes what every
        # request returns while the reported serving version stays
        # identical.
        "behaviour_splits": _behaviour_split_fingerprints(),
    }


def compute_serving_version(manifest: dict) -> str:
    """A single deployed-version identifier derived from the complete
    manifest, not any one artifact -- changing any serving-critical
    artifact or configuration value changes this. Keys sorted for a
    canonical, order-independent representation, so the same manifest
    always hashes to the same version regardless of construction order.
    """
    canonical = json.dumps(manifest, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]
