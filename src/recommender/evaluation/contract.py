
import pandas as pd

from recommender.paths import mind_small_path

# Frozen 2026-08-18. Every evaluation script imports these
# rather than redefining its own copy -- see docs/experiments/evaluation-protocol.md for
# what's frozen and why changing any of these invalidates prior comparisons.
SPLITS_DIR = mind_small_path("splits")
CATALOG_PATH = mind_small_path("train", "news.parquet")
TOP_K = 10


def load_split(name: str) -> pd.DataFrame:
    """Load one split's behaviors table: 'train', 'validation', or 'replay'."""
    return pd.read_parquet(SPLITS_DIR / name / "behaviors.parquet")


def load_catalog() -> pd.DataFrame:
    return pd.read_parquet(CATALOG_PATH)
