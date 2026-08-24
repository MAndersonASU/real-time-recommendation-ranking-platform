import pandas as pd

from recommender.reranking.freshness import (
    apply_freshness_quota,
    compute_age_days,
    compute_first_seen,
)


def _behaviors(rows):
    return pd.DataFrame(
        {
            "impression_id": [r[0] for r in rows],
            "user_id": [r[1] for r in rows],
            "time": pd.to_datetime([r[2] for r in rows]),
            "history": [r[3] for r in rows],
            "impressions": [r[4] for r in rows],
        }
    )


def test_first_seen_is_the_earliest_impression_time_an_item_appears_in():
    train = _behaviors(
        [
            (1, "U1", "2019-11-10 09:00:00", None, "A-1 B-0"),
            (2, "U2", "2019-11-09 08:00:00", None, "A-0"),  # earlier than row 1
            (3, "U3", "2019-11-11 10:00:00", None, "B-0"),
        ]
    )

    first_seen = compute_first_seen(train)

    assert first_seen["A"] == pd.Timestamp("2019-11-09 08:00:00")
    assert first_seen["B"] == pd.Timestamp("2019-11-10 09:00:00")


def test_age_days_is_unknown_not_zero_for_an_item_never_seen_in_train():
    """Regression test for a real bug, found by a follow-up audit: an
    item absent from `first_seen` used to be treated as age 0.0 --
    maximally fresh -- rather than a genuinely unknown age. That
    systematically favored items this project has no real history for
    under any freshness check, which is not a real freshness signal, and
    is fixed here by leaving it `NaN` instead of assuming a value.
    """
    first_seen = pd.Series({"A": pd.Timestamp("2019-11-10 00:00:00")})
    candidates = pd.DataFrame({"news_id": ["A", "Z"]})  # Z has no train history at all

    age = compute_age_days(candidates, pd.Timestamp("2019-11-12 00:00:00"), first_seen)

    assert age.loc[candidates["news_id"] == "A"].iloc[0] == 2.0
    assert pd.isna(age.loc[candidates["news_id"] == "Z"].iloc[0])


def test_quota_does_nothing_when_the_slate_already_has_enough_fresh_items():
    slate = pd.DataFrame(
        {"news_id": ["A", "B"], "score": [10, 9], "age_days": [0.1, 0.2]}
    )
    candidates = slate.copy()

    result = apply_freshness_quota(
        slate, candidates, score_column="score", min_fresh_in_slate=2, fresh_threshold_days=0.5
    )

    assert list(result["news_id"]) == ["A", "B"]


def test_quota_swaps_in_the_best_fresh_candidate_replacing_the_weakest_non_fresh_slate_item():
    slate = pd.DataFrame(
        {"news_id": ["A", "B"], "score": [10, 9], "age_days": [3.0, 4.0]}  # both stale
    )
    candidates = pd.DataFrame(
        {
            "news_id": ["A", "B", "C", "D"],
            "score": [10, 9, 8, 1],
            "age_days": [3.0, 4.0, 0.1, 0.2],  # C, D are fresh, C scores higher
        }
    )

    result = apply_freshness_quota(
        slate, candidates, score_column="score", min_fresh_in_slate=1, fresh_threshold_days=0.5
    )

    # B is the weakest (lowest-scored) non-fresh slate item -> replaced by
    # C, the best-scored fresh candidate not already in the slate.
    assert set(result["news_id"]) == {"A", "C"}
    assert len(result) == 2


def test_quota_never_treats_an_unknown_age_candidate_as_fresh():
    """Regression test for the same real bug at the quota level: before
    the fix, an item with no real first-seen time got age_days=0.0 and
    was therefore eligible to be swapped in as "fresh" -- exactly the
    systematic favoritism toward items with no real history the fix
    removes. An explicit NaN age_days must never be picked as a fresh
    swap-in candidate, only a genuinely known-fresh one.
    """
    import numpy as np

    slate = pd.DataFrame({"news_id": ["A", "B"], "score": [10, 9], "age_days": [3.0, 4.0]})
    candidates = pd.DataFrame(
        {
            "news_id": ["A", "B", "Z"],
            "score": [10, 9, 100],  # Z scores highest -- would win if wrongly treated as fresh
            "age_days": [3.0, 4.0, np.nan],  # Z's real age is unknown, not fresh
        }
    )

    result = apply_freshness_quota(
        slate, candidates, score_column="score", min_fresh_in_slate=1, fresh_threshold_days=0.5
    )

    # No genuinely fresh candidate exists (Z's age is unknown, not
    # fresh), so the slate must be left unchanged -- Z must never appear.
    assert list(result["news_id"]) == ["A", "B"]


def test_quota_leaves_slate_unchanged_when_no_fresh_alternative_exists_at_all():
    slate = pd.DataFrame({"news_id": ["A", "B"], "score": [10, 9], "age_days": [3.0, 4.0]})
    candidates = slate.copy()  # no fresh items anywhere among the candidates

    result = apply_freshness_quota(
        slate, candidates, score_column="score", min_fresh_in_slate=1, fresh_threshold_days=0.5
    )

    assert list(result["news_id"]) == ["A", "B"]
