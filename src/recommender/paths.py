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


class DataRootError(RuntimeError):
    """`RECOMMENDER_DATA_ROOT` is set to something unusable."""


def data_root() -> Path:
    """The directory holding processed data and trained artifacts.

    `RECOMMENDER_DATA_ROOT` wins when set, so a deployment that mounts
    its artifacts elsewhere does not need the repository layout. The
    container relies on exactly this: the package is installed into
    site-packages there, so the repository-root walk below would resolve
    under a directory that has never held any data.

    A **relative** override is refused rather than resolved. An earlier
    version called `.resolve()` on it and claimed that made it
    stable; it did not. `Path("some/data").resolve()` resolves against
    the current working directory *at the moment of the call*, so a
    relative override reintroduces precisely the drift this module
    exists to eliminate -- and silently, since each call still returns a
    confident absolute path. Refusing is the only behaviour that keeps
    the guarantee true.
    """
    override = os.environ.get("RECOMMENDER_DATA_ROOT")
    if override:
        path = Path(override)
        if not path.is_absolute():
            raise DataRootError(
                f"RECOMMENDER_DATA_ROOT must be an absolute path, got {override!r}. "
                "A relative value is resolved against the working directory on every "
                "lookup, so the same deployment would read different artifacts "
                "depending on where it was started."
            )
        return path
    return PROJECT_ROOT / "data"


def data_path(*parts: str) -> Path:
    """An absolute path beneath the data root."""
    return data_root().joinpath(*parts)


def mind_small_path(*parts: str) -> Path:
    return data_path("processed", "mind_small", *parts)
