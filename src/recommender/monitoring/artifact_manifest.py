import hashlib
import json
from pathlib import Path


def _file_fingerprint(path: Path) -> str:
    """First 12 hex characters of the real file's SHA-256, computed
    directly from the bytes actually on disk -- a genuine fingerprint of
    exactly which artifact is present, not a fabricated label that could
    silently drift from the real file.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def build_serving_artifact_manifest() -> dict:
    """Every artifact and pinned configuration value that determines
    what a live request actually gets served by. A prior version of
    this project's model-version identifier fingerprinted only the
    retrieval (two-tower) model file -- a real gap, found by a
    follow-up audit: the ranking model, the embedding model's own
    revision, the exact ranking feature schema, the catalog, and the
    reranking configuration can all change what a request actually
    receives without changing that one file at all.

    The Faiss index has no separate entry here: `build_serving_context`
    (`src/recommender/serving/pipeline.py`) never loads a saved index
    file for the live serving path -- it rebuilds the exact index
    in-memory from the retrieval model's own embeddings and the
    catalog, so its identity is already fully determined by
    `retrieval_model` and `catalog` below.
    """
    from recommender.evaluation.contract import CATALOG_PATH
    from recommender.explanation.generation import MODEL_NAME, MODEL_REVISION
    from recommender.ranking.train import MODEL_FEATURE_COLUMNS
    from recommender.ranking.train import MODEL_PATH as RANKING_MODEL_PATH
    from recommender.reranking.diversity import DEFAULT_MAX_PER_CATEGORY
    from recommender.reranking.freshness import (
        DEFAULT_FRESH_THRESHOLD_DAYS,
        DEFAULT_MIN_FRESH_IN_SLATE,
    )
    from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH

    return {
        "retrieval_model_sha256_prefix": _file_fingerprint(RETRIEVAL_MODEL_PATH),
        "ranking_model_sha256_prefix": _file_fingerprint(RANKING_MODEL_PATH),
        "ranking_feature_schema": list(MODEL_FEATURE_COLUMNS),
        "catalog_sha256_prefix": _file_fingerprint(CATALOG_PATH),
        "embedding_model_name": MODEL_NAME,
        "embedding_model_revision": MODEL_REVISION,
        "reranking_config": {
            "diversity_max_per_category": DEFAULT_MAX_PER_CATEGORY,
            "freshness_threshold_days": DEFAULT_FRESH_THRESHOLD_DAYS,
            "freshness_min_fresh_in_slate": DEFAULT_MIN_FRESH_IN_SLATE,
        },
    }


def compute_serving_version(manifest: dict) -> str:
    """A single, deployed-version identifier derived from the complete
    manifest, not any one artifact alone -- changing any serving-
    critical artifact or pinned configuration value changes this. Keys
    sorted for a canonical, order-independent representation, so the
    same real manifest always hashes to the same version regardless of
    dict construction order.
    """
    canonical = json.dumps(manifest, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]
