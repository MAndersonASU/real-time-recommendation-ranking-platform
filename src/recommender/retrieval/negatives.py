import numpy as np


def sample_negative_rows(
    user_id: str,
    positive_row: int,
    user_clicked_rows: dict,
    catalog_size: int,
    num_negatives: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Sample `num_negatives` catalog row indices as negatives for one
    positive (user, item) example. Rejects and redraws any candidate that
    is the positive item itself or an item this user is actually known to
    have clicked elsewhere in train -- an unfiltered random negative that
    happens to be something the user likes would be false training data,
    not harmless noise.
    """
    exclude = user_clicked_rows.get(user_id, set())

    # A real bug, found by audit: with no check here, a user excluded
    # from (or a catalog shrunk to) every single row leaves this loop
    # with literally zero valid candidates -- every draw rejected,
    # forever, since none can ever land outside `exclude | {positive_row}`.
    # At least one valid row existing is enough for the loop below to
    # terminate (it samples *with* replacement, so one safe row can fill
    # every remaining slot); zero valid rows is the one case it can
    # never recover from on its own.
    excluded_or_positive = exclude | {positive_row}
    available = catalog_size - len(excluded_or_positive)
    if available <= 0:
        raise ValueError(
            f"cannot sample any negative for user {user_id!r}: every one of the "
            f"{catalog_size} catalog rows is either the positive item or already "
            f"clicked by this user"
        )

    negatives = np.empty(num_negatives, dtype=np.int64)
    filled = 0
    while filled < num_negatives:
        candidates = rng.integers(0, catalog_size, size=num_negatives - filled)
        for row in candidates:
            if row != positive_row and row not in exclude:
                negatives[filled] = row
                filled += 1
                if filled >= num_negatives:
                    break
    return negatives


def sample_negatives_for_positives(
    user_ids: np.ndarray,
    positive_rows: np.ndarray,
    user_clicked_rows: dict,
    catalog_size: int,
    num_negatives: int,
    seed: int = 42,
) -> np.ndarray:
    """Sample negatives for a whole array of positive examples at once.
    Returns shape (len(user_ids), num_negatives).
    """
    rng = np.random.default_rng(seed)
    result = np.empty((len(user_ids), num_negatives), dtype=np.int64)
    for i, (user_id, positive_row) in enumerate(zip(user_ids, positive_rows, strict=True)):
        result[i] = sample_negative_rows(
            user_id, positive_row, user_clicked_rows, catalog_size, num_negatives, rng
        )
    return result
