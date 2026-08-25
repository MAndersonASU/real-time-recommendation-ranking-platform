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

CONTENT_ARTIFACT_PATH = Path("data/processed/mind_small/item_content.npz")


class ContentArtifactError(RuntimeError):
    """The persisted content artifact is missing, unreadable, or does not
    match the catalog it is being loaded against.

    Deliberately fatal rather than falling back to a fresh fit: silently
    refitting is the exact failure this module exists to prevent, and it
    would be invisible in the output.
    """


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
    if len(news) != content.shape[0]:
        raise ContentArtifactError(
            f"catalog has {len(news)} articles but the content matrix has "
            f"{content.shape[0]} rows"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        content=content.astype(np.float32),
        news_ids=news["news_id"].to_numpy().astype(str),
    )
    return path


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
    except Exception as exc:
        raise ContentArtifactError(f"content artifact at {path} is unreadable: {exc}") from exc

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
