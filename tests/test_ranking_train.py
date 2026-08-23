import numpy as np
import pandas as pd
import pytest
import skops.io as sio
from sklearn.metrics import roc_auc_score

from recommender.ranking.train import MODEL_FEATURE_COLUMNS, MODEL_PATH, train_ranking_model


def _synthetic_frame(n: int = 2000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    retrieval_score = rng.normal(size=n)
    clicked = (retrieval_score + rng.normal(scale=0.5, size=n) > 1.0).astype(int)
    return pd.DataFrame(
        {
            "retrieval_score": retrieval_score,
            "popularity": rng.normal(size=n),
            "category_match": rng.integers(0, 2, size=n).astype(float),
            "content_similarity": rng.normal(size=n),
            "user_history_length": rng.integers(0, 50, size=n).astype(float),
            "hour_of_day": rng.integers(0, 24, size=n).astype(float),
            "clicked": clicked,
        }
    )


def test_popularity_is_excluded_from_the_trained_models_features():
    assert "popularity" not in MODEL_FEATURE_COLUMNS


def test_train_ranking_model_learns_the_planted_signal():
    frame = _synthetic_frame()
    model = train_ranking_model(frame)

    pred = model.predict_proba(frame[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]
    auc = roc_auc_score(frame["clicked"], pred)

    assert auc > 0.75  # retrieval_score alone should give strong separation


def test_predict_proba_returns_valid_probabilities():
    frame = _synthetic_frame()
    model = train_ranking_model(frame)

    pred = model.predict_proba(frame[MODEL_FEATURE_COLUMNS].to_numpy())[:, 1]

    assert (pred >= 0).all() and (pred <= 1).all()


def test_retrieval_score_gets_a_positive_coefficient_when_it_drives_the_label():
    frame = _synthetic_frame()
    model = train_ranking_model(frame)

    coefficients = dict(
        zip(MODEL_FEATURE_COLUMNS, model.named_steps["logreg"].coef_[0], strict=True)
    )

    assert coefficients["retrieval_score"] > 0


def test_an_irrelevant_shuffled_feature_gets_a_much_smaller_coefficient():
    frame = _synthetic_frame()
    rng = np.random.default_rng(1)
    # hour_of_day plays no role in how `clicked` was generated -- shuffling
    # it again here just makes that independence explicit and unmistakable.
    frame["hour_of_day"] = rng.permutation(frame["hour_of_day"].to_numpy())

    model = train_ranking_model(frame)
    coefficients = dict(
        zip(MODEL_FEATURE_COLUMNS, model.named_steps["logreg"].coef_[0], strict=True)
    )

    assert abs(coefficients["hour_of_day"]) < abs(coefficients["retrieval_score"])


def test_model_path_uses_the_safe_skops_format_not_joblib_pickle():
    """Regression test for a real bug, found by audit: the ranking
    artifact used to be persisted as `ranking_model.joblib` -- a thin
    wrapper over pickle, so loading it means executing arbitrary code
    embedded in the file. Fails on the pre-fix code (`.joblib`) and
    passes once the real save path points at a `.skops` file instead.
    """
    assert MODEL_PATH.suffix == ".skops"


def test_trained_model_round_trips_through_skops_with_identical_predictions(tmp_path):
    """A real bug, found by audit: the ranking artifact used to be
    saved and loaded with joblib -- a thin wrapper over pickle, so
    loading it means executing arbitrary code embedded in the file, not
    just reading data. skops (`sio` here) is the fix: it serializes and
    reloads the same real, trained Pipeline without ever executing code
    from the file. Confirms the round trip is lossless, not just that
    it doesn't crash.
    """
    frame = _synthetic_frame()
    model = train_ranking_model(frame)
    path = tmp_path / "model.skops"

    sio.dump(model, path)
    # No `trusted=` list: the real production model (Pipeline of
    # StandardScaler + LogisticRegression) is already fully covered by
    # skops's own default-safe types -- confirmed directly against this
    # project's actual trained artifact before this fix was made.
    reloaded = sio.load(path)

    x = frame[MODEL_FEATURE_COLUMNS].to_numpy()
    assert np.array_equal(model.predict_proba(x), reloaded.predict_proba(x))


def test_skops_load_refuses_an_unrecognized_type_by_default(tmp_path):
    """Demonstrates the actual safety property the fix relies on,
    without needing to construct a real malicious payload: an object
    containing a type skops doesn't already know is safe is rejected by
    `sio.load` unless the caller explicitly opts in via `trusted=`, the
    exact opposite of joblib/pickle's "silently execute whatever the
    file contains."
    """

    class _NotAKnownSafeType:
        pass

    path = tmp_path / "untrusted.skops"
    sio.dump({"payload": _NotAKnownSafeType()}, path)

    with pytest.raises(sio.exceptions.UntrustedTypesFoundException):
        sio.load(path)
