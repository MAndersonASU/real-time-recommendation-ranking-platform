import numpy as np
import pandas as pd

from recommender.evaluation.ablations import ABLATION_MATRIX, NO_RETRIEVAL_SCORE_FEATURES
from recommender.ranking.train import train_ranking_model


def test_ablation_matrix_covers_all_five_named_components():
    components = {spec.component for spec in ABLATION_MATRIX}
    assert components == {
        "retrieval features",
        "ranker features",
        "reranking",
        "recent streaming features",
        "cache/index settings",
    }


def test_two_ablations_are_new_this_step_and_three_reuse_tracked_runs():
    statuses = [spec.status for spec in ABLATION_MATRIX]
    assert statuses.count("new_this_step") == 2
    assert statuses.count("reuses_existing_tracked_run") == 3


def test_no_retrieval_score_features_excludes_retrieval_score_and_popularity():
    assert "retrieval_score" not in NO_RETRIEVAL_SCORE_FEATURES
    assert "popularity" not in NO_RETRIEVAL_SCORE_FEATURES
    assert "category_match" in NO_RETRIEVAL_SCORE_FEATURES
    assert "content_similarity" in NO_RETRIEVAL_SCORE_FEATURES
    assert "user_history_length" in NO_RETRIEVAL_SCORE_FEATURES
    assert "hour_of_day" in NO_RETRIEVAL_SCORE_FEATURES


def _synthetic_frame(n: int = 2000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    retrieval_score = rng.normal(size=n)
    content_similarity = rng.normal(size=n)
    clicked = (content_similarity + rng.normal(scale=0.5, size=n) > 1.0).astype(int)
    return pd.DataFrame(
        {
            "retrieval_score": retrieval_score,
            "popularity": rng.normal(size=n),
            "category_match": rng.integers(0, 2, size=n).astype(float),
            "content_similarity": content_similarity,
            "user_history_length": rng.integers(0, 50, size=n).astype(float),
            "hour_of_day": rng.integers(0, 24, size=n).astype(float),
            "clicked": clicked,
        }
    )


def test_train_ranking_model_accepts_a_reduced_feature_set():
    frame = _synthetic_frame()
    model = train_ranking_model(frame, feature_columns=NO_RETRIEVAL_SCORE_FEATURES)

    pred = model.predict_proba(frame[NO_RETRIEVAL_SCORE_FEATURES].to_numpy())[:, 1]

    assert (pred >= 0).all() and (pred <= 1).all()


def test_reduced_feature_set_still_learns_the_planted_content_similarity_signal():
    frame = _synthetic_frame()
    model = train_ranking_model(frame, feature_columns=NO_RETRIEVAL_SCORE_FEATURES)

    coefficients = dict(
        zip(NO_RETRIEVAL_SCORE_FEATURES, model.named_steps["logreg"].coef_[0], strict=True)
    )

    assert coefficients["content_similarity"] > 0
