from pathlib import Path

import pandas as pd

# Frozen 2026-08-18, Phase 2 Step 2.5. Every evaluation script imports these
# rather than redefining its own copy -- see docs/evaluation-protocol.md for
# what's frozen and why changing any of these invalidates prior comparisons.
SPLITS_DIR = Path("data/processed/mind_small/splits")
CATALOG_PATH = Path("data/processed/mind_small/train/news.parquet")
TOP_K = 10


def load_split(name: str) -> pd.DataFrame:
    """Load one split's behaviors table: 'train', 'validation', or 'replay'."""
    return pd.read_parquet(SPLITS_DIR / name / "behaviors.parquet")


def load_catalog() -> pd.DataFrame:
    return pd.read_parquet(CATALOG_PATH)
