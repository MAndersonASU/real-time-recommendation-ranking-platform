from pathlib import Path

from recommender.evaluation.contract import CATALOG_PATH, SPLITS_DIR, TOP_K


def test_frozen_evaluation_constants():
    # Guards against an accidental, silent change to the frozen protocol --
    # any real change to these values must also touch this test.
    assert TOP_K == 10
    assert SPLITS_DIR == Path("data/processed/mind_small/splits")
    assert CATALOG_PATH == Path("data/processed/mind_small/train/news.parquet")
