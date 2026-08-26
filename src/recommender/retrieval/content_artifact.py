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

from recommender.paths import mind_small_path
from recommender.retrieval.features import CONTENT_DIM

CONTENT_ARTIFACT_PATH = mind_small_path("item_content.npz")

# Bumped whenever the stored fields or the checksum definition change,
# so an artifact written under an older contract is refused rather than
# read as if it followed the current one.
CONTENT_SCHEMA_VERSION = 1

REQUIRED_FIELDS = ("content", "news_ids", "schema_version", "feature_width", "content_sha256")


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
        schema_version=np.int64(CONTENT_SCHEMA_VERSION),
        feature_width=np.int64(content.shape[1]),
        content_sha256=np.array(_canonical_checksum(content, news_ids)),
    )
    return path


def _legacy_matrix_checksum(content: np.ndarray) -> str:
    """The pre-schema digest: matrix bytes only.

    Retained solely to verify artifacts written under the old format.
    Its weakness is the reason those artifacts are refused by default --
    identical bytes under a different id ordering, shape or dtype
    produce the same value, so it confirms the payload survived transit
    and nothing about what the payload means.
    """
    return hashlib.sha256(np.ascontiguousarray(content, dtype=np.float32).tobytes()).hexdigest()


def _canonical_checksum(
    content: np.ndarray, news_ids: np.ndarray, schema_version: int = CONTENT_SCHEMA_VERSION
) -> str:
    """SHA-256 over everything that makes the artifact what it is.

    The previous checksum covered the matrix bytes alone, which left
    three ways to corrupt an artifact without the checksum noticing:
    reorder the article ids, change the declared shape, or reinterpret
    the payload under a different dtype. The bytes are identical in each
    case, so a bytes-only digest reports agreement while the artifact
    now means something different.

    Each component is length-prefixed and tagged. Without separators,
    ids `["ab", "c"]` and `["a", "bc"]` serialise to the same bytes, and
    a shape of (2, 3) and (3, 2) would too.
    """
    digest = hashlib.sha256()
    digest.update(f"content-artifact-v{schema_version}\n".encode())
    digest.update(f"shape={content.shape[0]}x{content.shape[1]}\n".encode())
    digest.update(f"dtype={np.dtype(np.float32).str}\n".encode())
    digest.update(f"ids={len(news_ids)}\n".encode())
    for article_id in news_ids:
        digest.update(f"{len(str(article_id))}:{article_id}\n".encode())
    digest.update(b"matrix\n")
    digest.update(np.ascontiguousarray(content, dtype=np.float32).tobytes())
    return digest.hexdigest()


def load_item_content(
    news: pd.DataFrame, path: Path = CONTENT_ARTIFACT_PATH, allow_legacy: bool = False
) -> np.ndarray:
    """Loads the persisted content matrix and validates it against the
    catalog actually in use.

    Every stored field is **required**, and `allow_legacy` defaults to
    False. An earlier version treated the metadata as optional -- absent
    schema version, feature width or checksum simply skipped the
    corresponding check -- so the weakest artifact in existence got the
    least validation, which is exactly backwards. An artifact written
    before those fields existed cannot be verified at all, and a loader
    that accepts it is asserting something it did not check.

    `allow_legacy=True` exists for a deliberate migration and is never
    used by the serving path. It skips the metadata checks and says so;
    it does not make an unverifiable artifact verified.
    """
    if not path.exists():
        raise ContentArtifactError(
            f"no persisted content artifact at {path}. Build it with "
            f"`python -m recommender.retrieval.train`, which fits the "
            f"transformation once and saves it."
        )
    try:
        with np.load(path, allow_pickle=False) as data:
            present = set(data.files)
            content = data["content"] if "content" in present else None
            stored_ids = data["news_ids"] if "news_ids" in present else None
            stored_version = int(data["schema_version"]) if "schema_version" in present else None
            stored_width = int(data["feature_width"]) if "feature_width" in present else None
            stored_checksum = str(data["content_sha256"]) if "content_sha256" in present else None
    except Exception as exc:
        raise ContentArtifactError(f"content artifact at {path} is unreadable: {exc}") from exc

    missing = [field for field in REQUIRED_FIELDS if field not in present]
    if missing:
        if not allow_legacy:
            raise ContentArtifactError(
                f"content artifact at {path} is missing required fields {missing}. It "
                f"predates the current schema (v{CONTENT_SCHEMA_VERSION}) and cannot be "
                f"verified. Rebuild it with `python -m recommender.retrieval.train`, or "
                f"pass allow_legacy=True to load it unverified -- which the serving path "
                f"never does."
            )
        if content is None or stored_ids is None:
            raise ContentArtifactError(
                f"content artifact at {path} has no payload: missing {missing}"
            )

    if stored_version is not None and stored_version != CONTENT_SCHEMA_VERSION:
        raise ContentArtifactError(
            f"content artifact declares schema version {stored_version}, but this build "
            f"reads version {CONTENT_SCHEMA_VERSION}. The stored fields or the checksum "
            f"definition differ; rebuild rather than reinterpret."
        )

    # The artifact's own declared width is checked against the
    # application's expectation, not merely against the payload. Trusting
    # the declaration alone let a self-consistent artifact -- correct
    # checksum, matching metadata -- load with a feature width this build
    # cannot use.
    if stored_width is not None and stored_width != CONTENT_DIM:
        raise ContentArtifactError(
            f"content artifact declares feature width {stored_width}, but this "
            f"build expects {CONTENT_DIM}"
        )
    _validate_matrix(np.asarray(content), expected_width=CONTENT_DIM)
    _validate_ids(np.asarray(stored_ids))

    if stored_checksum is not None:
        if stored_version is None:
            # A pre-schema artifact stores the old bytes-only digest, so
            # it must be checked with that function. Verifying it with
            # the canonical one would report every legacy artifact as
            # corrupt, which is a different claim from "unverifiable".
            actual = _legacy_matrix_checksum(np.asarray(content))
            description = "the legacy checksum covers matrix bytes only"
        else:
            actual = _canonical_checksum(
                np.asarray(content), np.asarray(stored_ids).astype(str), stored_version
            )
            description = (
                "the checksum covers schema version, shape, dtype, article ordering "
                "and matrix bytes, so this reports a reordering or a metadata change "
                "as well as a corrupted payload"
            )
        if actual != stored_checksum:
            raise ContentArtifactError(
                f"content artifact checksum does not match its contents -- "
                f"{description}."
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
