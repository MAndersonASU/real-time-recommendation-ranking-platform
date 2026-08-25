
from recommender.evaluation.contract import CATALOG_PATH, SPLITS_DIR, TOP_K


def test_frozen_evaluation_constants():
    # Guards against an accidental, silent change to the frozen protocol --
    # any real change to these values must also touch this test.
    assert TOP_K == 10
    # Anchored to the repository root rather than the working
    # directory, so the frozen contract is the *location within the
    # data root*, not a path that changes with the caller's shell.
    assert SPLITS_DIR.parts[-4:] == ("data", "processed", "mind_small", "splits")
    assert SPLITS_DIR.is_absolute()
    assert CATALOG_PATH.parts[-5:] == (
        "data", "processed", "mind_small", "train", "news.parquet"
    )
    assert CATALOG_PATH.is_absolute()
