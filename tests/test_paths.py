"""Where the data live, and the one deployment where the default is wrong.

`recommender.paths` anchors artifacts to the repository root so that a
serving version cannot change with the caller's working directory. That
anchor is computed from the package's own file location, which is right
for a source checkout and wrong inside the container, where the package
is installed into `site-packages` and the repository-root walk lands on
`/usr/local/lib/python3.11`.

That is not hypothetical: it shipped, and the container job caught it
only after the image had been built and started. The last test here
pins the fix in place.
"""

import os
import re
from pathlib import Path

import pytest

import recommender.paths as paths_module
from recommender.paths import PROJECT_ROOT, data_path, data_root, mind_small_path

DOCKERFILE = Path("Dockerfile")


def test_the_data_root_does_not_move_with_the_working_directory(monkeypatch, tmp_path):
    """The original defect. Data paths were relative to the process
    working directory, so the same deployment hashed every artifact
    normally from the repository root and reported every one `absent`
    from anywhere else -- and the derived serving version changed with
    the caller's shell.
    """
    monkeypatch.delenv("RECOMMENDER_DATA_ROOT", raising=False)
    before = data_root()

    monkeypatch.chdir(tmp_path)

    assert data_root() == before
    assert data_root().is_absolute()


def test_an_explicit_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("RECOMMENDER_DATA_ROOT", str(tmp_path))

    assert data_root() == tmp_path.resolve()
    assert mind_small_path("train", "news.parquet") == (
        tmp_path.resolve() / "processed" / "mind_small" / "train" / "news.parquet"
    )


def test_a_relative_override_is_refused(monkeypatch, tmp_path):
    """A relative override reintroduces exactly the working-directory
    dependence the anchor exists to remove.

    An earlier version resolved it and claimed that made it stable.
    `Path("some/data").resolve()` resolves against the working directory
    at the moment of the call, so the value changed with `cd` while
    still looking like a confident absolute path. This test is what
    caught that; refusing is the only behaviour that keeps the guarantee
    true.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RECOMMENDER_DATA_ROOT", "some/data")

    # Reached through the module, not a name bound at import time.
    # tests/test_artifact_manifest.py reloads recommender.paths, which
    # rebinds DataRootError to a new class object -- an exception
    # imported here beforehand then no longer matches the one raised,
    # and the test fails only when the suite runs in full.
    with pytest.raises(paths_module.DataRootError, match="must be an absolute path"):
        paths_module.data_root()


def test_the_default_root_is_the_repository_not_the_package(monkeypatch):
    """`PROJECT_ROOT` must be the repository root in a source checkout.
    In an installed layout this same walk lands elsewhere, which is why
    the container sets an explicit override (tested below).
    """
    monkeypatch.delenv("RECOMMENDER_DATA_ROOT", raising=False)

    assert (PROJECT_ROOT / "pyproject.toml").exists()
    assert data_path("processed") == PROJECT_ROOT / "data" / "processed"


def test_the_container_sets_an_explicit_data_root():
    """Regression test for a real production failure.

    Without this the image resolves artifacts under
    `/usr/local/lib/python3.11/data/...`, which never exists, and the
    API dies during startup with a FileNotFoundError from deep inside
    pandas. The container mounts its data at `/app/data`, so the image
    has to say so rather than inferring it from an install location that
    pip controls.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    match = re.search(r"^ENV RECOMMENDER_DATA_ROOT=(\S+)", dockerfile, re.MULTILINE)

    assert match, "the image must set RECOMMENDER_DATA_ROOT explicitly"
    assert match.group(1) == "/app/data", (
        f"data root is {match.group(1)!r} but the volume mounts at /app/data"
    )


def test_the_container_data_root_matches_where_the_volume_is_mounted():
    """The two halves of the same fact, kept in agreement: the image
    declares a data root, and the Dockerfile creates and owns that same
    directory for the unprivileged user.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "mkdir -p /app/data" in dockerfile
    assert os.path.basename("/app/data") == "data"
