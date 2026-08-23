import random

import numpy as np
import torch


def set_seed(seed: int) -> None:
    """Seeds every real source of randomness training actually draws
    from. A real bug, found by audit: this previously seeded only
    Python's own `random` module, while the two-tower model's weight
    initialization and its DataLoader's shuffle order both draw from
    torch's global RNG -- neither seeded by this function, and this
    function was never even called from the real training entrypoint
    (`recommender.retrieval.train`) in the first place. Two runs with an
    identical dataset and an identical seed were not reproducible.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
