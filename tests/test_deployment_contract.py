"""Guards the specific claim DEPLOYMENT-CONTRACT-62 found broken:
`docs/architecture.md` said Redis is optional and API startup does not
gate on it, but `docker-compose.yml`'s `api` service had
`depends_on: redis: condition: service_healthy`, which blocks container
startup until Redis reports healthy -- a real, live-verified gap between
the doc and the file, not a documentation wording issue.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
BUILD_IMAGE_SCRIPT = REPO_ROOT / "build-image.sh"


def _api_service_block() -> str:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    # Service blocks are top-level keys under `services:`, indented two
    # spaces, e.g. "  api:" -- slice from there to the next such key (or
    # end of file) to isolate just this service's own configuration.
    match = re.search(r"^  api:\n(.*?)(?=^  \w+:|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "docker-compose.yml has no top-level `api:` service"
    return match.group(1)


def test_api_service_does_not_gate_startup_on_redis_health():
    api_block = _api_service_block()

    # A structural check, not a bare substring match: the fix's own
    # explanatory comment legitimately mentions "service_healthy" by
    # name (to say the api service no longer has it), so this looks for
    # the real YAML shape -- a `depends_on:` block naming `redis:` with
    # `condition: service_healthy` under it -- not just the phrase
    # appearing anywhere in the block's prose.
    match = re.search(
        r"^\s*depends_on:\s*\n(?:^\s*#.*\n)*^\s*redis:\s*\n\s*condition:\s*service_healthy",
        api_block,
        re.MULTILINE,
    )
    assert match is None, (
        "the api service must not block container startup on Redis's health check -- "
        "build_serving_context never connects to Redis during startup, only "
        "constructs a lazily-connected client object, so there is no real dependency "
        "here to gate on (recommender.serving.pipeline.build_serving_context)"
    )


def test_dockerfile_does_not_claim_compose_computes_the_commit_automatically():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "does this automatically" not in text, (
        "Compose cannot run a shell command inline for a build arg -- it only "
        "forwards GIT_COMMIT_SHA when the caller's own host environment already "
        "has it set, it does not compute `git rev-parse HEAD` itself"
    )


def test_build_image_wrapper_exists_and_is_valid_bash():
    assert BUILD_IMAGE_SCRIPT.exists(), (
        "build-image.sh (the committed wrapper that actually calls "
        "`git rev-parse HEAD` before building) is missing"
    )

    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:
        return  # matches tests/test_orchestration_scripts.py's own skip-if-absent
    result = subprocess.run(
        [bash, "-n", str(BUILD_IMAGE_SCRIPT)], capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr


def test_build_image_wrapper_actually_calls_git_rev_parse_head():
    text = BUILD_IMAGE_SCRIPT.read_text(encoding="utf-8")

    assert "git rev-parse HEAD" in text
    assert "GIT_COMMIT_SHA=" in text
    assert "docker compose build" in text


# --- DEPLOYMENT-CONTRACT-62 follow-up: a dirty image-affecting path
# must refuse the build, not just warn and continue ---


def _prepared_worktree(worktree_dir: str) -> None:
    """`git worktree add` checks out committed `HEAD` -- it cannot see
    this script's own uncommitted, in-progress fix, so the checked-out
    copy of build-image.sh is overwritten with the real one on disk
    right now. The worktree's only remaining job is to supply an
    independent, controllable git-status baseline (a real, clean commit
    history) for the dirty-tree check to run against -- not to also
    freeze the script under test at some older, possibly-unfixed commit.
    """
    import shutil

    subprocess.run(
        ["git", "worktree", "add", "--detach", worktree_dir, "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
    )
    shutil.copyfile(BUILD_IMAGE_SCRIPT, Path(worktree_dir) / "build-image.sh")


def _remove_worktree(worktree_dir: str) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", worktree_dir],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False,
    )


def test_dirty_image_affecting_file_refuses_the_build_not_just_warns():
    """Regression test for a real bug, found by audit: the dirty-tree
    check printed a warning to stderr and then unconditionally
    continued to `docker compose build api` -- Docker would copy the
    actual (dirty) working-tree contents into the image while it is
    labeled with the clean HEAD commit, the same provenance mismatch
    this project refuses outright for an evaluation report produced
    from a dirty tree. Fails on the pre-fix code (the real build runs
    and "Built" appears in the output, alongside the old warning) and
    passes once a dirty image-affecting path exits the script before
    reaching the build at all -- proven by real `docker compose build`
    output never appearing, not by a stubbed-out `docker`, since a real
    build here is fast enough (cached layers) to run directly.

    Runs against a real, isolated `git worktree` checkout of HEAD, not
    the ambient working tree this test suite itself runs in (which may
    already be legitimately dirty from unrelated in-progress work) --
    so this exercises the real script's real git-status logic, just
    against a tree whose starting state this test fully controls.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")

    with tempfile.TemporaryDirectory() as worktree_dir:
        _prepared_worktree(worktree_dir)
        try:
            # A real, uncommitted change under one of the image-affecting
            # paths (src/) -- exactly the class of change the Dockerfile's
            # `COPY src/ ./src/` would silently pick up.
            dirty_file = Path(worktree_dir) / "src" / "recommender" / "_dirty_marker_for_test.py"
            dirty_file.write_text("# intentionally uncommitted, for this test only\n", encoding="utf-8")

            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=120, check=False,
            )

            assert result.returncode != 0, (
                f"expected a nonzero exit refusing the dirty build, got 0. "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert "refusing to build" in result.stderr
            assert "_dirty_marker_for_test.py" in result.stderr
            assert "Built" not in result.stdout, (
                "the real docker build ran despite the dirty file -- "
                f"stdout={result.stdout!r}"
            )
        finally:
            _remove_worktree(worktree_dir)


def test_a_clean_tree_still_reaches_the_real_build_invocation():
    """The complement of the test above: proves the dirty-tree check
    isn't so broad it refuses a genuinely clean build too -- a real
    `docker compose build api` actually runs and succeeds.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    if shutil.which("docker") is None:
        pytest.skip("no docker on PATH")

    with tempfile.TemporaryDirectory() as worktree_dir:
        _prepared_worktree(worktree_dir)
        try:
            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=300, check=False,
            )

            assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert "refusing to build" not in result.stderr
        finally:
            _remove_worktree(worktree_dir)


def test_a_dirty_file_outside_image_affecting_paths_does_not_refuse():
    """A change to something the image doesn't contain (docs here) must
    not block the build -- the check is scoped to what actually affects
    the image, not "any uncommitted change anywhere in the repo".
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    if shutil.which("docker") is None:
        pytest.skip("no docker on PATH")

    with tempfile.TemporaryDirectory() as worktree_dir:
        _prepared_worktree(worktree_dir)
        try:
            docs_dir = Path(worktree_dir) / "docs"
            docs_dir.mkdir(exist_ok=True)
            (docs_dir / "_dirty_marker_for_test.md").write_text("scratch\n", encoding="utf-8")

            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=300, check=False,
            )

            assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert "refusing to build" not in result.stderr
        finally:
            _remove_worktree(worktree_dir)
