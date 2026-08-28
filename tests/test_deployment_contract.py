"""Guards the specific claim DEPLOYMENT-CONTRACT-62 found broken:
`docs/architecture.md` said Redis is optional and API startup does not
gate on it, but `docker-compose.yml`'s `api` service had
`depends_on: redis: condition: service_healthy`, which blocks container
startup until Redis reports healthy -- a real, live-verified gap between
the doc and the file, not a documentation wording issue.
"""

import re
from pathlib import Path

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
