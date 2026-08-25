import numpy as np
import pandas as pd
import pytest

from recommender.retrieval.content_artifact import (
    ContentArtifactError,
    content_artifact_fingerprint,
    load_item_content,
    save_item_content,
)
from recommender.retrieval.features import CONTENT_DIM, build_item_content_matrix

NEWS = pd.DataFrame(
    {
        "news_id": [f"n{i}" for i in range(6)],
        "category": ["sports", "sports", "tech", "tech", "news", "news"],
        "subcategory": ["football", "tennis", "ai", "gadgets", "world", "local"],
        "title": [
            "striker scores twice", "tennis final result", "ai model breakthrough",
            "new phone released", "world summit begins", "local council meets",
        ],
        "abstract": [""] * 6,
    }
)


def test_saved_content_round_trips_identically(tmp_path):
    """The whole point of persisting this artifact: what serving loads
    must be bit-for-bit what training fitted, not a re-derivation.
    """
    path = tmp_path / "item_content.npz"
    fitted = build_item_content_matrix(NEWS)

    save_item_content(NEWS, fitted, path=path)
    loaded = load_item_content(NEWS, path=path)

    assert np.array_equal(fitted.astype(np.float32), loaded)


def test_training_and_serving_read_identical_vectors_from_one_artifact(tmp_path):
    """Simulates the real split of responsibilities: training fits and
    saves once; a separate later process (index build, evaluation,
    serving) only ever loads. Both must see the same coordinates.

    This is the regression that matters. TruncatedSVD axes are defined
    only up to sign and ordering, so an independent refit at serving time
    can produce a different-but-valid basis -- feeding the trained model
    coordinates it never saw, with no shape error and no exception.
    """
    path = tmp_path / "item_content.npz"

    # Training-time: fit and persist.
    training_matrix = build_item_content_matrix(NEWS)
    save_item_content(NEWS, training_matrix, path=path)

    # Serving-time: load only.
    serving_matrix = load_item_content(NEWS, path=path)

    assert np.array_equal(training_matrix.astype(np.float32), serving_matrix)
    # And every individual article's vector matches, not just the whole
    # array -- an ordering bug would keep the array equal in aggregate
    # only if the ids also moved, which the loader separately rejects.
    for row, news_id in enumerate(NEWS["news_id"]):
        assert np.array_equal(training_matrix[row].astype(np.float32), serving_matrix[row]), news_id


def test_missing_artifact_raises_instead_of_silently_refitting(tmp_path):
    """A missing artifact must fail loudly. Falling back to a fresh fit
    would reintroduce exactly the basis-mismatch this module prevents,
    and would do it invisibly.
    """
    with pytest.raises(ContentArtifactError, match="no persisted content artifact"):
        load_item_content(NEWS, path=tmp_path / "does-not-exist.npz")


def test_corrupt_artifact_raises(tmp_path):
    path = tmp_path / "item_content.npz"
    path.write_bytes(b"this is not a valid npz archive")

    with pytest.raises(ContentArtifactError, match="unreadable"):
        load_item_content(NEWS, path=path)


def test_row_count_mismatch_is_rejected(tmp_path):
    """A catalog with more articles than the artifact was built from."""
    path = tmp_path / "item_content.npz"
    save_item_content(NEWS, build_item_content_matrix(NEWS), path=path)

    bigger = pd.concat([NEWS, NEWS.iloc[[0]].assign(news_id="n99")], ignore_index=True)
    with pytest.raises(ContentArtifactError, match="rows but the catalog has"):
        load_item_content(bigger, path=path)


def test_reordered_catalog_is_rejected(tmp_path):
    """Rows are positional, so a reordered catalog would silently give
    every article another article's content vector. The stored ids exist
    to make that detectable rather than plausible-looking.
    """
    path = tmp_path / "item_content.npz"
    save_item_content(NEWS, build_item_content_matrix(NEWS), path=path)

    reordered = NEWS.iloc[::-1].reset_index(drop=True)
    with pytest.raises(ContentArtifactError, match="ordering does not match"):
        load_item_content(reordered, path=path)


def test_saving_a_mismatched_matrix_is_rejected(tmp_path):
    path = tmp_path / "item_content.npz"
    wrong_shape = np.zeros((len(NEWS) + 3, 8), dtype=np.float32)

    with pytest.raises(ContentArtifactError, match="content matrix has"):
        save_item_content(NEWS, wrong_shape, path=path)


def test_fingerprint_is_none_when_absent_and_changes_with_content(tmp_path):
    absent = tmp_path / "nope.npz"
    assert content_artifact_fingerprint(path=absent) is None

    path = tmp_path / "item_content.npz"
    save_item_content(NEWS, build_item_content_matrix(NEWS), path=path)
    first = content_artifact_fingerprint(path=path)
    assert first is not None and len(first) == 12

    altered = build_item_content_matrix(NEWS)
    altered[0, 0] += 1.0
    save_item_content(NEWS, altered, path=path)
    assert content_artifact_fingerprint(path=path) != first


# --- Structural validation -------------------------------------------
#
# Only row count and article order were previously checked, so a
# structurally broken matrix reached serving and produced silently wrong
# retrieval instead of an error.


def _good_matrix(rows: int | None = None):
    return np.zeros((rows or len(NEWS), CONTENT_DIM), dtype=np.float32)


def test_saving_a_one_dimensional_array_is_rejected(tmp_path):
    with pytest.raises(ContentArtifactError, match="two-dimensional"):
        save_item_content(NEWS, np.zeros(len(NEWS), dtype=np.float32), path=tmp_path / "a.npz")


def test_saving_the_wrong_feature_width_is_rejected(tmp_path):
    wrong = np.zeros((len(NEWS), CONTENT_DIM // 2), dtype=np.float32)

    with pytest.raises(ContentArtifactError, match="feature width"):
        save_item_content(NEWS, wrong, path=tmp_path / "a.npz")


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_saving_non_finite_values_is_rejected(tmp_path, bad_value):
    matrix = _good_matrix()
    matrix[0, 0] = bad_value

    with pytest.raises(ContentArtifactError, match="NaN or infinite"):
        save_item_content(NEWS, matrix, path=tmp_path / "a.npz")


def test_saving_a_non_floating_dtype_is_rejected(tmp_path):
    integers = np.zeros((len(NEWS), CONTENT_DIM), dtype=np.int32)

    with pytest.raises(ContentArtifactError, match="floating dtype"):
        save_item_content(NEWS, integers, path=tmp_path / "a.npz")


def test_a_float64_matrix_is_narrowed_rather_than_refused(tmp_path):
    """A fitted transform naturally yields float64; narrowing it to the
    storage dtype is intended, unlike a non-floating dtype.
    """
    path = save_item_content(
        NEWS, np.zeros((len(NEWS), CONTENT_DIM), dtype=np.float64), path=tmp_path / "a.npz"
    )

    assert load_item_content(NEWS, path=path).dtype == np.float32


def test_loading_a_stored_matrix_with_the_wrong_dtype_is_rejected(tmp_path):
    path = tmp_path / "a.npz"
    np.savez(
        path,
        content=np.zeros((len(NEWS), CONTENT_DIM), dtype=np.float64),
        news_ids=NEWS["news_id"].to_numpy().astype(str),
    )

    with pytest.raises(ContentArtifactError, match="must be float32"):
        load_item_content(NEWS, path=path)


def test_duplicate_article_ids_are_rejected(tmp_path):
    """Rows are positional, so a duplicate id makes the article-to-row
    mapping ambiguous rather than merely redundant.
    """
    duplicated = NEWS.copy()
    duplicated.loc[duplicated.index[-1], "news_id"] = duplicated.loc[0, "news_id"]

    with pytest.raises(ContentArtifactError, match="duplicate article ids"):
        save_item_content(duplicated, _good_matrix(), path=tmp_path / "a.npz")


def test_an_empty_article_id_is_rejected(tmp_path):
    blanked = NEWS.copy()
    blanked.loc[0, "news_id"] = "   "

    with pytest.raises(ContentArtifactError, match="empty article id"):
        save_item_content(blanked, _good_matrix(), path=tmp_path / "a.npz")


def test_a_tampered_payload_is_caught_by_the_stored_checksum(tmp_path):
    """Shape and dtype can still look correct after corruption, so the
    artifact records a checksum over its own bytes.
    """
    path = tmp_path / "a.npz"
    save_item_content(NEWS, _good_matrix(), path=path)

    with np.load(path, allow_pickle=False) as data:
        stored = {k: data[k] for k in data.files}
    tampered = stored["content"].copy()
    tampered[0, 0] = 1.5
    stored["content"] = tampered
    np.savez(path, **stored)

    with pytest.raises(ContentArtifactError, match="checksum does not match"):
        load_item_content(NEWS, path=path)
