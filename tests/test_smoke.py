import random

import recommender
from recommender.seed import set_seed


def test_package_imports():
    assert recommender is not None


def test_set_seed_is_deterministic():
    set_seed(42)
    first = random.random()
    set_seed(42)
    second = random.random()
    assert first == second
