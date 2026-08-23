import pandas as pd

from recommender.evaluation.tuning_fold import (
    chronological_tuning_split_impression_ids,
    split_rows_by_impression_ids,
    split_train_for_tuning,
)


def _synthetic_rows(n_impressions: int = 200, candidates_per_impression: int = 3) -> pd.DataFrame:
    rows = []
    for impression_id in range(n_impressions):
        for candidate_index in range(candidates_per_impression):
            rows.append(
                {
                    "impression_id": impression_id,
                    "news_id": f"n{impression_id}_{candidate_index}",
                    "clicked": 1 if candidate_index == 0 else 0,
                    "popularity": float(candidate_index),
                }
            )
    return pd.DataFrame(rows)


def test_split_never_puts_one_impressions_candidates_in_both_halves():
    rows = _synthetic_rows()

    fit_rows, tune_rows = split_train_for_tuning(rows)

    fit_impressions = set(fit_rows["impression_id"])
    tune_impressions = set(tune_rows["impression_id"])
    assert fit_impressions.isdisjoint(tune_impressions)


def test_split_covers_every_row_exactly_once():
    rows = _synthetic_rows()

    fit_rows, tune_rows = split_train_for_tuning(rows)

    assert len(fit_rows) + len(tune_rows) == len(rows)


def test_split_is_deterministic_given_the_same_seed():
    rows = _synthetic_rows()

    fit_a, tune_a = split_train_for_tuning(rows, seed=123)
    fit_b, tune_b = split_train_for_tuning(rows, seed=123)

    assert list(fit_a["impression_id"]) == list(fit_b["impression_id"])
    assert list(tune_a["impression_id"]) == list(tune_b["impression_id"])


def test_split_produces_a_real_nonempty_tune_fold_at_the_default_fraction():
    rows = _synthetic_rows(n_impressions=500)

    fit_rows, tune_rows = split_train_for_tuning(rows)

    # Not asserting an exact count (the split is randomized per
    # impression, not row-exact) -- just that a real, substantial
    # held-out fold actually exists, roughly in the expected range.
    assert len(tune_rows) > 0
    assert len(fit_rows) > 0
    tune_fraction = len(tune_rows) / len(rows)
    assert 0.1 < tune_fraction < 0.3


def test_split_never_leaks_a_specific_impressions_rows_across_the_boundary():
    """A real, targeted regression check for the exact failure mode a
    row-level (rather than impression-level) split would produce: one
    impression's own candidates ending up partly in fit, partly in tune.
    """
    rows = _synthetic_rows(n_impressions=50, candidates_per_impression=10)

    fit_rows, tune_rows = split_train_for_tuning(rows)

    for impression_id in rows["impression_id"].unique():
        in_fit = (fit_rows["impression_id"] == impression_id).sum()
        in_tune = (tune_rows["impression_id"] == impression_id).sum()
        assert in_fit == 0 or in_tune == 0  # never split across both


def _synthetic_behaviors(n_impressions: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "impression_id": range(n_impressions),
            "user_id": [f"u{i}" for i in range(n_impressions)],
            "time": pd.date_range("2019-11-09", periods=n_impressions, freq="h"),
        }
    )


def test_chronological_split_puts_only_the_earliest_impressions_in_fit():
    behaviors = _synthetic_behaviors(n_impressions=100)

    fit_ids, tune_ids = chronological_tuning_split_impression_ids(behaviors, fraction=0.2)

    assert fit_ids.isdisjoint(tune_ids)
    assert len(fit_ids) + len(tune_ids) == 100
    # The fold boundary is a real point in time, not a random draw: every
    # fit id's impression_id (== its chronological rank here, by
    # construction) must be less than every tune id's.
    assert max(fit_ids) < min(tune_ids)


def test_chronological_split_respects_the_requested_fraction():
    behaviors = _synthetic_behaviors(n_impressions=1000)

    fit_ids, tune_ids = chronological_tuning_split_impression_ids(behaviors, fraction=0.2)

    assert len(tune_ids) == 200
    assert len(fit_ids) == 800


def test_split_rows_by_impression_ids_applies_the_given_partition():
    rows = _synthetic_rows(n_impressions=10, candidates_per_impression=2)
    fit_ids = {0, 1, 2, 3, 4}
    tune_ids = {5, 6, 7, 8, 9}

    fit_rows, tune_rows = split_rows_by_impression_ids(rows, fit_ids, tune_ids)

    assert set(fit_rows["impression_id"]) == fit_ids
    assert set(tune_rows["impression_id"]) == tune_ids
    assert len(fit_rows) + len(tune_rows) == len(rows)
