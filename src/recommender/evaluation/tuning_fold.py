import numpy as np
import pandas as pd

TUNE_FOLD_SEED = 20260823
TUNE_FOLD_FRACTION = 0.2


def split_train_for_tuning(
    train_rows: pd.DataFrame, fraction: float = TUNE_FOLD_FRACTION, seed: int = TUNE_FOLD_SEED
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A deterministic, held-out-for-tuning-only fold carved from
    `train`'s own rows, split by `impression_id` (never by row alone,
    so one impression's candidates never end up split across both
    halves) -- real infrastructure fixing a real bug: three feature and
    hyperparameter decisions in this project (dropping `popularity`
    from the ranking model, the diversity category cap, the freshness
    threshold) were originally chosen by looking at measurements on
    `validation`, which was then also used for every final reported
    metric -- model/hyperparameter-selection leakage, even though no
    gradient-based training ever touched validation directly
    (docs/evaluation-protocol.md).

    Carved from `train` alone, by a fixed seed, so it never overlaps
    with `validation` or `replay` by construction. Any future feature
    or hyperparameter decision should be checked against this fold, not
    against validation, which stays reserved for final reporting only.
    A disclosed, smaller residual limitation: the currently-deployed
    ranking model was already fit on all of `train`, including these
    same rows, before this fold existed -- this fold's own real value
    is confirming whether the *decisions* (not the model's fitted
    weights) hold up on data that was never used to make them, which is
    exactly what leaked. See `docs/evaluation-integrity.md`.
    """
    impression_ids = train_rows["impression_id"].unique()
    rng = np.random.default_rng(seed)
    is_tune_impression = rng.random(len(impression_ids)) < fraction
    tune_impression_ids = set(impression_ids[is_tune_impression])

    is_tune_row = train_rows["impression_id"].isin(tune_impression_ids)
    fit_rows = train_rows[~is_tune_row].reset_index(drop=True)
    tune_rows = train_rows[is_tune_row].reset_index(drop=True)
    return fit_rows, tune_rows
