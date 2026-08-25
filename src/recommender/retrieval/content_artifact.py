"""Persistence for the fitted article-content transformation.

The item tower is trained against a particular latent coordinate system:
TF-IDF over each article's title and abstract, reduced by `TruncatedSVD`
(`recommender.retrieval.features.build_item_content_matrix`). SVD axes
are only defined up to sign and ordering, and a randomized solver, a
different scikit-learn version, or a different platform can all produce
a different -- individually valid -- basis for the same corpus.

Refitting that transformation at serving time therefore risks feeding
the trained model coordinates from a basis it never saw, with no error
raised anywhere: the shapes still match and the numbers still look
reasonable. Fitting happens once, during artifact construction, and
every other stage loads these exact vectors instead.

The finalized matrix is persisted rather than the fitted transformer
objects. Both are defensible; this choice avoids depending on
scikit-learn's pickle compatibility across versions, and what serving
actually needs is the per-article coordinates, not the ability to
transform new text.
"""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from recommender.retrieval.features import CONTENT_DIM

CONTENT_ARTIFACT_PATH = Path("data/processed/mind_small/item_content.npz")


class ContentArtifactError(RuntimeError):
    """The persisted content artifact is missing, unreadable, or does not
    match the catalog it is being loaded against.

    Deliberately fatal rather than falling back to a fresh fit: silently
    refitting is the exact failure this module exists to prevent, and it
    would be invisible in the output.
    """


def _validate_matrix(content: np.ndarray, expected_width: int | None = None) -> None:
    """Rejects a matrix that is structurally unusable.

    Each check corresponds to a way a corrupt artifact previously
    reached serving without complaint: only row count and article order
    were verified, so a one-dimensional array, the wrong feature width,
    a non-float dtype or NaN/Inf values all passed through and produced
    silently wrong retrieval instead of an error.
    """
    if content.ndim != 2:
        raise ContentArtifactError(
            f"content matrix must be two-dimensional, got {content.ndim} dimension(s)"
        )
    if expected_width is not None and content.shape[1] != expected_width:
        raise ContentArtifactError(
            f"content matrix has feature width {content.shape[1]}, expected {expected_width}"
        )
    if content.dtype != np.float32:
        raise ContentArtifactError(
            f"content matrix must be float32, got {content.dtype}"
        )
    if not np.isfinite(content).all():
        raise ContentArtifactError(
            "content matrix contains NaN or infinite values; an embedding built from "
            "these would be silently meaningless rather than wrong in a detectable way"
        )


def _validate_ids(news_ids: np.ndarray) -> None:
    if news_ids.size == 0:
        raise ContentArtifactError("content artifact has no article ids")
    stripped = np.char.strip(news_ids.astype(str))
    if (stripped == "").any():
        raise ContentArtifactError("content artifact contains an empty article id")
    unique, counts = np.unique(stripped, return_counts=True)
    if unique.size != news_ids.size:
        duplicated = unique[counts > 1][:3].tolist()
        raise ContentArtifactError(
            f"content artifact contains duplicate article ids (e.g. {duplicated}); "
            f"rows are positional, so a duplicate makes the mapping ambiguous"
        )


def save_item_content(
    news: pd.DataFrame, content: np.ndarray, path: Path = CONTENT_ARTIFACT_PATH
) -> Path:
    """Persists the content matrix alongside the article ids it was built
    from, in catalog row order.

    The ids are stored with the matrix because the rows are positional:
    a matrix loaded against a catalog in a different order would be
    silently wrong, and storing the ordering is what makes that
    detectable.
    """
    content = np.asarray(content)
    # A floating input is cast to the storage dtype: a fitted transform
    # naturally produces float64 and narrowing it is intended. Anything
    # non-floating is a different kind of mistake and is refused rather
    # than silently reinterpreted.
    if not np.issubdtype(content.dtype, np.floating):
        raise ContentArtifactError(
            f"content matrix must have a floating dtype, got {content.dtype}"
        )
    if content.ndim == 2:
        content = content.astype(np.float32, copy=False)
    _validate_matrix(content, expected_width=CONTENT_DIM)
    if len(news) != content.shape[0]:
        raise ContentArtifactError(
            f"catalog has {len(news)} articles but the content matrix has "
            f"{content.shape[0]} rows"
        )
    news_ids = news["news_id"].to_numpy().astype(str)
    _validate_ids(news_ids)

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        content=content,
        news_ids=news_ids,
        # Recorded so a loader can check what the artifact claims to be,
        # rather than inferring its schema from its shape.
        feature_width=np.int64(content.shape[1]),
        content_sha256=np.array(_matrix_checksum(content)),
    )
    return path


def _matrix_checksum(content: np.ndarray) -> str:
    """SHA-256 over the matrix bytes, so a corrupted payload is
    detectable even when its shape and dtype still look correct.
    """
    return hashlib.sha256(np.ascontiguousarray(content, dtype=np.float32).tobytes()).hexdigest()


def load_item_content(
    news: pd.DataFrame, path: Path = CONTENT_ARTIFACT_PATH
) -> np.ndarray:
    """Loads the persisted content matrix and validates it against the
    catalog actually in use.

    Three ways this can be wrong are all checked rather than assumed:
    the artifact is absent, it is unreadable, or its article ordering
    and dimensions do not line up with the catalog being served.
    """
    if not path.exists():
        raise ContentArtifactError(
            f"no persisted content artifact at {path}. Build it with "
            f"`python -m recommender.retrieval.train`, which fits the "
            f"transformation once and saves it."
        )
    try:
        with np.load(path, allow_pickle=False) as data:
            content = data["content"]
            stored_ids = data["news_ids"]
            _stored_width = int(data["feature_width"]) if "feature_width" in data else None
            _stored_checksum = str(data["content_sha256"]) if "content_sha256" in data else None
    except Exception as exc:
        raise ContentArtifactError(f"content artifact at {path} is unreadable: {exc}") from exc

    stored_width = int(data_width) if (data_width := _stored_width) is not None else None
    _validate_matrix(np.asarray(content), expected_width=stored_width or CONTENT_DIM)
    _validate_ids(np.asarray(stored_ids))

    if _stored_checksum is not None and _matrix_checksum(content) != _stored_checksum:
        raise ContentArtifactError(
            "content artifact checksum does not match its payload; the file changed "
            "after it was written"
        )

    catalog_ids = news["news_id"].to_numpy().astype(str)
    if content.shape[0] != len(catalog_ids):
        raise ContentArtifactError(
            f"content artifact has {content.shape[0]} rows but the catalog has "
            f"{len(catalog_ids)} articles"
        )
    if not np.array_equal(stored_ids, catalog_ids):
        raise ContentArtifactError(
            "content artifact article ordering does not match the catalog. The "
            "matrix is positional, so this would silently mis-assign every "
            "article's content vector."
        )
    return content.astype(np.float32)


def content_artifact_fingerprint(path: Path = CONTENT_ARTIFACT_PATH) -> str | None:
    """SHA-256 prefix of the persisted artifact, for the serving manifest.
    Returns None when the artifact is absent, so manifest construction can
    report its absence rather than raising.
    """
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
