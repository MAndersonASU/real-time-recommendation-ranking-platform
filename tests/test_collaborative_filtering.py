import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.ranking.baselines import (
    build_collaborative_factors,
    compute_popularity,
    rank_by_collaborative_filtering,
)


def _behaviors(rows):
    return pd.DataFrame(
        {
            "impression_id": [r[0] for r in rows],
            "user_id": [r[1] for r in rows],
            "time": pd.to_datetime([r[2] for r in rows]),
            "history": [None] * len(rows),
            "impressions": [r[3] for r in rows],
        }
    )


def test_rank_by_collaborative_filtering_recovers_a_clean_two_group_pattern():
    # Two independent click groups: {U1, U2} always click A and C together;
    # {U3, U4} always click B and D together. This matrix has rank exactly
    # 2, so TruncatedSVD(n_components=2) reconstructs it (near-)exactly --
    # a robust invariant regardless of sign/rotation ambiguity in the SVD.
    train = _behaviors(
        [
            (1, "U1", "2019-11-09 09:00:00", "A-1 X-0"),
            (2, "U1", "2019-11-09 10:00:00", "C-1 X-0"),
            (3, "U2", "2019-11-09 09:00:00", "A-1 X-0"),
            (4, "U2", "2019-11-09 10:00:00", "C-1 X-0"),
            (5, "U3", "2019-11-09 09:00:00", "B-1 X-0"),
            (6, "U3", "2019-11-09 10:00:00", "D-1 X-0"),
            (7, "U4", "2019-11-09 09:00:00", "B-1 X-0"),
            (8, "U4", "2019-11-09 10:00:00", "D-1 X-0"),
        ]
    )
    popularity = compute_popularity(train)
    user_factors, item_factors, user_row_by_id, item_row_by_id = build_collaborative_factors(
        train, n_components=2
    )

    # U1 belongs to the {A, C} group; candidates are B (other group) and C (own group).
    validation = _behaviors([(100, "U1", "2019-11-10 09:00:00", "B-0 C-0")])
    exploded = explode_impressions(validation)

    ordered = rank_by_collaborative_filtering(
        exploded, "U1", user_factors, item_factors, user_row_by_id, item_row_by_id, popularity
    )

    assert list(ordered["news_id"]) == ["C", "B"]  # own-group item scores higher


def test_falls_back_to_popularity_for_a_user_never_seen_in_training():
    # Two distinct users, not one. With a single user the interaction
    # matrix has no between-user variance, so TruncatedSVD divides by a
    # zero total and emits a RuntimeWarning while computing
    # explained_variance_ratio_. That warning said nothing about the
    # behaviour under test -- it was an artifact of a degenerate
    # fixture. A second real user removes it without weakening the
    # assertion, which is about an entirely *unseen* user either way.
    train = _behaviors(
        [
            (1, "U1", "2019-11-09 10:00:00", "A-1 B-0"),
            (2, "U1", "2019-11-09 11:00:00", "A-1 B-0"),
            (3, "U1", "2019-11-09 12:00:00", "B-1 A-0"),
            (4, "U2", "2019-11-09 13:00:00", "A-1 B-0"),
        ]
    )
    popularity = compute_popularity(train)  # A=3, B=1
    user_factors, item_factors, user_row_by_id, item_row_by_id = build_collaborative_factors(
        train, n_components=1
    )

    validation = _behaviors([(100, "U_NEW", "2019-11-10 09:00:00", "B-0 A-0")])
    exploded = explode_impressions(validation)

    ordered = rank_by_collaborative_filtering(
        exploded, "U_NEW", user_factors, item_factors, user_row_by_id, item_row_by_id, popularity
    )

    assert list(ordered["news_id"]) == ["A", "B"]  # popularity order: A(2) > B(1)
