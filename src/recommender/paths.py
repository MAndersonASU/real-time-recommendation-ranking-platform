"""One place that decides where this project's data lives.

Every data path used to be relative to the process working directory, so
the same deployment reported a different serving version depending on
where the command was run from: from the repository root every artifact
hashed normally, and from anywhere else every artifact reported `absent`
and the derived version changed. A version identifier that depends on
the caller's shell is not a version identifier.

Paths are therefore anchored to the repository root, or to an explicit
`RECOMMENDER_DATA_ROOT` when the data live somewhere else -- a container
bind-mount, a shared volume -- rather than being inferred from wherever
the process happens to start.
"""

import os
from pathlib import Path

# src/recommender/paths.py -> src/recommender -> src -> repository root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """The directory holding processed data and trained artifacts.

    `RECOMMENDER_DATA_ROOT` wins when set, so a deployment that mounts
    its artifacts elsewhere does not need the repository layout. Its
    value is resolved, so a relative override still yields an absolute
    path and cannot drift with the working directory either.
    """
    override = os.environ.get("RECOMMENDER_DATA_ROOT")
    if override:
        return Path(override).resolve()
    return PROJECT_ROOT / "data"


def data_path(*parts: str) -> Path:
    """An absolute path beneath the data root."""
    return data_root().joinpath(*parts)


def mind_small_path(*parts: str) -> Path:
    return data_path("processed", "mind_small", *parts)
