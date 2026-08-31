"""Guards the specific claim DEPLOYMENT-CONTRACT-62 found broken:
`docs/architecture.md` said Redis is optional and API startup does not
gate on it, but `docker-compose.yml`'s `api` service had
`depends_on: redis: condition: service_healthy`, which blocks container
startup until Redis reports healthy -- a real, live-verified gap between
the doc and the file, not a documentation wording issue.
"""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
BUILD_IMAGE_SCRIPT = REPO_ROOT / "build-image.sh"


def _docker_daemon_available() -> bool:
    """`shutil.which("docker")` only proves the CLI binary exists, not
    that a daemon is actually reachable behind it (a real, seen state
    locally: Docker Desktop installed but not currently running) --
    `docker info` is the cheap, real way to tell the two apart.
    """
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=10, check=False
    )
    return result.returncode == 0


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
    right now. If that overwrite actually changed anything (the fix is
    still uncommitted in this repository), it's committed *inside the
    worktree* -- a throwaway commit against its own disposable history,
    never touching this repository's real one -- so the worktree's own
    `HEAD` genuinely reflects the updated script. Once the fix is
    itself committed here, the copy is a no-op and there is nothing to
    commit; `git commit` would exit nonzero for "nothing to commit" in
    that case, so the commit is skipped rather than run unconditionally.
    Either way, the worktree ends up clean relative to its own HEAD --
    which matters now that the dirty check covers the whole tree rather
    than an enumerated list, so a build-image.sh that was left
    perpetually "modified" relative to the worktree's HEAD would make
    every "clean tree" test scenario below refuse regardless of what
    it's actually testing.
    """
    import shutil

    subprocess.run(
        ["git", "worktree", "add", "--detach", worktree_dir, "HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=True,
    )
    shutil.copyfile(BUILD_IMAGE_SCRIPT, Path(worktree_dir) / "build-image.sh")
    if subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_dir, capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip():
        subprocess.run(
            ["git", "commit", "-am", "test: sync build-image.sh with the working copy under test"],
            cwd=worktree_dir, capture_output=True, text=True, timeout=30, check=True,
        )


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
    if not _docker_daemon_available():
        pytest.skip("no docker daemon reachable")

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


def test_a_project_directory_ending_in_underscore_still_builds():
    """Regression test for a real bug, found by a real CI failure: with
    no explicit Compose project name, Compose derives one from the
    checkout directory's own basename and appends "-api" to form the
    image tag. A basename ending in "_" (exactly what
    `tempfile.TemporaryDirectory()` produces on a real, observed CI
    run) makes that tag "..._-api", which Docker rejects outright:
    "invalid tag ... invalid reference format" -- reproduced directly
    against a real checkout at such a path, before this fix. A real
    deployment's checkout directory name is exactly as unpredictable as
    this. Fails on the pre-fix script (real build failure, not a
    refusal) and passes once an explicit, always-valid project name is
    pinned regardless of the directory it happens to run from.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    if not _docker_daemon_available():
        pytest.skip("no docker daemon reachable")

    base = tempfile.mkdtemp()
    worktree_dir = base + "_"
    assert not os.path.exists(worktree_dir)
    _prepared_worktree(worktree_dir)
    try:
        result = subprocess.run(
            [bash, "build-image.sh"],
            cwd=worktree_dir, capture_output=True, text=True, timeout=300, check=False,
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "invalid reference format" not in result.stdout + result.stderr
    finally:
        _remove_worktree(worktree_dir)
        shutil.rmtree(base, ignore_errors=True)


def test_a_dirty_file_anywhere_in_the_tree_refuses_the_build():
    """Regression test for a real bug identified during verification of
    the prior fix: that version scoped the dirty check to a hand-enumerated
    list of paths (src/, Dockerfile, pyproject.toml,
    requirements-lock.txt), which missed real build inputs --
    docker-compose.yml (the build context, args and Dockerfile path are
    all defined there) and .dockerignore (controls what actually
    reaches the build context) were not checked at all, so a dirty
    change to either still built and shipped unnoticed. Requiring the
    *entire* tree clean is the fix: it cannot miss a build input an
    enumerated list forgot to name. A dirty file under docs/ -- which
    does not affect the image at all -- now also refuses, a deliberate,
    accepted cost of not depending on the list staying complete.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")

    with tempfile.TemporaryDirectory() as worktree_dir:
        _prepared_worktree(worktree_dir)
        try:
            docs_dir = Path(worktree_dir) / "docs"
            docs_dir.mkdir(exist_ok=True)
            (docs_dir / "_dirty_marker_for_test.md").write_text("scratch\n", encoding="utf-8")

            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=120, check=False,
            )

            assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert "refusing to build" in result.stderr
            assert "_dirty_marker_for_test.md" in result.stderr
        finally:
            _remove_worktree(worktree_dir)


def test_a_dirty_docker_compose_file_refuses_the_build():
    """`docker-compose.yml` itself defines the build context, args and
    Dockerfile path for the very image this script builds -- a dirty
    copy is exactly as image-affecting as a dirty Dockerfile, and an
    enumerated-paths check that named the latter but not the former
    would still miss this.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")

    with tempfile.TemporaryDirectory() as worktree_dir:
        _prepared_worktree(worktree_dir)
        try:
            compose_file = Path(worktree_dir) / "docker-compose.yml"
            with compose_file.open("a", encoding="utf-8") as f:
                f.write("\n# intentionally uncommitted, for this test only\n")

            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=120, check=False,
            )

            assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert "refusing to build" in result.stderr
            assert "docker-compose.yml" in result.stderr
        finally:
            _remove_worktree(worktree_dir)


def test_a_dirty_dockerignore_file_refuses_the_build():
    """`.dockerignore` controls what actually reaches the build context
    Docker sees -- a dirty copy can change what a `COPY` instruction
    picks up just as much as editing the Dockerfile itself.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")

    with tempfile.TemporaryDirectory() as worktree_dir:
        _prepared_worktree(worktree_dir)
        try:
            dockerignore = Path(worktree_dir) / ".dockerignore"
            with dockerignore.open("a", encoding="utf-8") as f:
                f.write("\n# intentionally uncommitted, for this test only\n")

            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=120, check=False,
            )

            assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert "refusing to build" in result.stderr
            assert ".dockerignore" in result.stderr
        finally:
            _remove_worktree(worktree_dir)


def test_invocation_from_an_unrelated_directory_still_operates_on_this_repo():
    """Regression test for a real bug identified during follow-up
    verification: every command in this script (git status/rev-parse,
    docker compose
    reading docker-compose.yml) used to be relative to the caller's
    cwd, not the script's own location. Reproduced directly: running
    `bash build-image.sh` from a plain scratch directory failed with a
    raw `fatal: not a git repository` instead of operating on this
    repository at all -- and from inside a *different* git repository,
    it would have silently read that repository's commit and status
    instead of this one's, which is worse than an outright failure.

    Runs the worktree's own copy of the script (not this repo's) with
    `cwd` set to a third, unrelated scratch directory -- neither the
    worktree nor this repository -- and confirms it still correctly
    resolves and reports *the worktree's own* dirty file, proving the
    anchor to the script's own directory actually works, not merely
    that it no longer crashes.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")

    with (
        tempfile.TemporaryDirectory() as worktree_dir,
        tempfile.TemporaryDirectory() as unrelated_cwd,
    ):
        _prepared_worktree(worktree_dir)
        try:
            dirty_file = Path(worktree_dir) / "src" / "recommender" / "_dirty_marker_for_test.py"
            dirty_file.write_text("# intentionally uncommitted, for this test only\n", encoding="utf-8")

            result = subprocess.run(
                [bash, str(Path(worktree_dir) / "build-image.sh")],
                cwd=unrelated_cwd, capture_output=True, text=True, timeout=120, check=False,
            )

            assert "not a git repository" not in result.stderr, (
                f"the script did not resolve its own repository from an unrelated cwd: "
                f"stderr={result.stderr!r}"
            )
            assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert "refusing to build" in result.stderr
            assert "_dirty_marker_for_test.py" in result.stderr
        finally:
            _remove_worktree(worktree_dir)


_EVIL_COMPOSE_CONTENT = (
    "services:\n"
    "  decoy:\n"
    "    image: evil-image-not-the-real-one\n"
    "    build:\n"
    "      context: .\n"
    "      dockerfile: Dockerfile.evil\n"
)

# A unique marker inside the real, committed docker-compose.yml's `api`
# service block -- used by the fake `docker` below to prove the `-f`
# value it received really is this repository's own file, by content,
# rather than by comparing path strings across a script that may run
# under a POSIX-style path (MSYS/Git Bash on Windows) against a Python
# `tempfile` path in Windows form, which would not compare equal even
# when they name the same location.
REAL_COMPOSE_MARKER = "container_name: recommender-api"


def _fake_docker_dir(capture_file: Path) -> Path:
    """A directory holding a stand-in `docker` executable that, instead
    of running a real build, records which `-f`/`--project-directory`
    values it was called with and -- resolved entirely inside bash, on
    whatever machine runs the test, never compared against a Python-side
    path string -- whether those values actually name this repository's
    own committed `docker-compose.yml` and its own directory. Exits 0
    unconditionally, so the wrapper script's own exit code reflects
    only whether *it* reached and issued the docker compose invocation,
    not whether a real image build happened to succeed.

    Lets `test_compose_file_env_var_cannot_redirect_the_build_configuration`
    and its unrelated-directory variant assert a real success exit code
    without depending on a reachable Docker daemon -- the separate
    `test_a_clean_tree_still_reaches_the_real_build_invocation` above
    covers a real end-to-end build against a real daemon.
    """
    stub_dir = Path(tempfile.mkdtemp())
    stub = stub_dir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "f_value=\"\"\n"
        "proj_value=\"\"\n"
        "prev=\"\"\n"
        "for arg in \"$@\"; do\n"
        "  case \"$prev\" in\n"
        "    -f) f_value=\"$arg\" ;;\n"
        "    --project-directory) proj_value=\"$arg\" ;;\n"
        "  esac\n"
        "  prev=\"$arg\"\n"
        "done\n"
        "{\n"
        "  if [ -n \"$f_value\" ] && [ -f \"$f_value\" ] && "
        f"grep -qF {shlex.quote(REAL_COMPOSE_MARKER)} \"$f_value\"; then\n"
        "    echo \"f_value_is_real_compose_file=yes\"\n"
        "  else\n"
        "    echo \"f_value_is_real_compose_file=no ($f_value)\"\n"
        "  fi\n"
        "  if [ -n \"$proj_value\" ] && [ -f \"$proj_value/Dockerfile\" ]; then\n"
        "    echo \"proj_value_is_real_repo_dir=yes\"\n"
        "  else\n"
        "    echo \"proj_value_is_real_repo_dir=no ($proj_value)\"\n"
        "  fi\n"
        f"}} > {shlex.quote(str(capture_file))}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub_dir


def test_compose_file_env_var_cannot_redirect_the_build_configuration():
    """Regression test for a real bug identified during follow-up
    verification: a bare `docker compose build api`, with no explicit
    `-f`/`--project-directory`,
    resolves its configuration from the *environment* as much as from
    this script's own directory. `COMPOSE_FILE` -- including one set
    from the gitignored `.env` file Compose reads automatically -- can
    redirect the whole build to an unrelated configuration without ever
    making this repository's own working tree dirty, so the clean-tree
    refusal above never sees it.

    Reproduced directly: with `COMPOSE_FILE` pointed at a compose file
    that defines no `api` service at all, a bare `docker compose build
    api` (no explicit `-f`) fails with "no such service: api" -- proof
    it read the wrong file entirely, not this repository's own
    docker-compose.yml.

    A fake `docker` on `PATH` (ahead of the real one) stands in for the
    real build, so this test can assert the script's own exit code
    reaches 0 -- proving it actually issued the build, not merely that
    one specific error string is absent, which an unrelated failure
    could also satisfy -- and that the `-f`/`--project-directory`
    values it received are genuinely this repository's own
    docker-compose.yml and its own directory, without needing a
    reachable Docker daemon for a real build.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    if shutil.which("docker") is None:
        pytest.skip("no docker CLI on PATH")

    with (
        tempfile.TemporaryDirectory() as worktree_dir,
        tempfile.TemporaryDirectory() as evil_dir,
        tempfile.TemporaryDirectory() as capture_dir,
    ):
        _prepared_worktree(worktree_dir)
        try:
            evil_compose = Path(evil_dir) / "evil-compose.yml"
            evil_compose.write_text(_EVIL_COMPOSE_CONTENT, encoding="utf-8")
            capture_file = Path(capture_dir) / "docker_stub_capture.txt"
            fake_docker_dir = _fake_docker_dir(capture_file)

            env = dict(
                os.environ,
                COMPOSE_FILE=str(evil_compose),
                PATH=f"{fake_docker_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            )
            result = subprocess.run(
                [bash, "build-image.sh"],
                cwd=worktree_dir, capture_output=True, text=True, timeout=120, check=False, env=env,
            )

            assert "no such service: api" not in result.stderr, (
                "COMPOSE_FILE redirected the build away from this repository's own "
                f"docker-compose.yml: stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert result.returncode == 0, (
                f"expected the committed Compose configuration to build successfully; "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            capture = capture_file.read_text(encoding="utf-8")
            assert "f_value_is_real_compose_file=yes" in capture, capture
            assert "proj_value_is_real_repo_dir=yes" in capture, capture
        finally:
            _remove_worktree(worktree_dir)


def test_invocation_from_an_unrelated_directory_with_compose_file_set_still_uses_this_repos_compose_file():
    """Both external-review gaps at once: an unrelated invocation
    directory and a `COMPOSE_FILE` pointed elsewhere, together -- proof
    neither alone, nor combined, can redirect the build away from this
    repository's own committed docker-compose.yml. See the test above
    for why a fake `docker` stands in for the real build.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    if shutil.which("docker") is None:
        pytest.skip("no docker CLI on PATH")

    with (
        tempfile.TemporaryDirectory() as worktree_dir,
        tempfile.TemporaryDirectory() as evil_dir,
        tempfile.TemporaryDirectory() as unrelated_cwd,
        tempfile.TemporaryDirectory() as capture_dir,
    ):
        _prepared_worktree(worktree_dir)
        try:
            evil_compose = Path(evil_dir) / "evil-compose.yml"
            evil_compose.write_text(_EVIL_COMPOSE_CONTENT, encoding="utf-8")
            capture_file = Path(capture_dir) / "docker_stub_capture.txt"
            fake_docker_dir = _fake_docker_dir(capture_file)

            env = dict(
                os.environ,
                COMPOSE_FILE=str(evil_compose),
                PATH=f"{fake_docker_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            )
            result = subprocess.run(
                [bash, str(Path(worktree_dir) / "build-image.sh")],
                cwd=unrelated_cwd, capture_output=True, text=True, timeout=120, check=False, env=env,
            )

            assert "not a git repository" not in result.stderr
            assert "no such service: api" not in result.stderr, (
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert result.returncode == 0, (
                f"expected the committed Compose configuration to build successfully; "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            capture = capture_file.read_text(encoding="utf-8")
            assert "f_value_is_real_compose_file=yes" in capture, capture
            assert "proj_value_is_real_repo_dir=yes" in capture, capture
        finally:
            _remove_worktree(worktree_dir)
