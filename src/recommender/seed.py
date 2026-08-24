import random

import numpy as np
import torch


def set_seed(seed: int) -> None:
    """Seeds every real source of randomness training actually draws
    from: Python's own `random` module, numpy, and torch's global RNG,
    which the two-tower model's weight initialization and its
    DataLoader's shuffle order both draw from. Called from the real
    training entrypoint (`recommender.retrieval.train.train_model`), so
    two runs given an identical dataset and an identical seed are
    reproducible.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
