"""DATA-PATH-CONSISTENCY-63: `RECOMMENDER_DATA_ROOT` (`recommender.paths`)
is supposed to be the one override that moves every data path this
project uses, so a deployment that mounts its artifacts elsewhere never
needs the repository layout. Before this fix, only the serving-critical
artifact paths (the trained model, index, ranking pipeline) actually
went through `data_path()`/`mind_small_path()` -- every ingestion,
evaluation, and tracking module still built its own path from a
`Path("data/...")` literal, relative to the process's working
directory, so the override silently didn't apply to most of the
project's own commands.

This test doesn't hand-list the modules that must comply (a list like
that goes stale the moment a new evaluation module is added, silently
losing coverage). It statically discovers every module-level constant
built from `data_path(...)` or `mind_small_path(...)` across
`src/recommender/`, then -- in a real subprocess, with a genuinely
different working directory and a temporary `RECOMMENDER_DATA_ROOT` --
imports every one of them and checks the resulting path actually
resolves beneath that override.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "recommender"

_ASSIGNMENT_RE = re.compile(
    r"^([A-Z][A-Z0-9_]*)\s*=\s*(?:data_path|mind_small_path)\(", re.MULTILINE
)


def _discover_data_path_constants() -> list[tuple[str, str]]:
    """Returns (dotted_module_name, constant_name) for every module-level
    constant anywhere under src/recommender/ built directly from
    data_path(...) or mind_small_path(...).
    """
    found = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path.name == "paths.py":
            continue  # PROJECT_ROOT there is the fixed anchor itself, not data-root-relative
        text = path.read_text(encoding="utf-8")
        for match in _ASSIGNMENT_RE.finditer(text):
            relative = path.relative_to(REPO_ROOT / "src").with_suffix("")
            module = ".".join(relative.parts)
            found.append((module, match.group(1)))
    return found


DISCOVERED = _discover_data_path_constants()

_HARDCODED_DATA_PATH_RE = re.compile(r'Path\(\s*["\']data[/\\]')


def test_no_module_builds_a_data_path_from_a_hardcoded_literal():
    """The direct complement to the subprocess check below: that one
    only re-checks constants already built from data_path/mind_small_path,
    so a constant that regresses back to a bare `Path("data/...")`
    literal would simply drop out of its discovery and go unnoticed. This
    catches that regression by construction -- a `Path("data/...")`
    literal anywhere under src/recommender/ (paths.py's own
    `PROJECT_ROOT / "data"` fallback is the one legitimate exception,
    and uses `/` division, not `Path("data/...")`, so it never matches).
    """
    offenders = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if _HARDCODED_DATA_PATH_RE.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"these build a data path from a hardcoded 'data/...' literal instead of "
        f"data_path()/mind_small_path() (recommender.paths), so RECOMMENDER_DATA_ROOT "
        f"silently would not apply to them: {offenders}"
    )


def test_discovery_finds_every_known_data_path_module():
    # A coarse sanity floor on the discovery regex itself: if this drops
    # to a handful, the regex broke, not that most of the project
    # stopped using data_path/mind_small_path.
    assert len(DISCOVERED) >= 35, (
        f"only found {len(DISCOVERED)} data_path/mind_small_path constants -- "
        "the discovery regex may be broken"
    )


def test_every_discovered_constant_resolves_beneath_a_recommender_data_root_override():
    with tempfile.TemporaryDirectory() as override_root, tempfile.TemporaryDirectory() as cwd:
        script_lines = [
            "import importlib, json",
            "results = {}",
        ]
        for module, constant in DISCOVERED:
            script_lines.append(
                f"results[{module + '.' + constant!r}] = "
                f"str(importlib.import_module({module!r}).{constant})"
            )
        script_lines.append("print(json.dumps(results))")
        script = "\n".join(script_lines)

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=cwd,
            env={
                "RECOMMENDER_DATA_ROOT": override_root,
                # A minimal environment, not the full one this process
                # inherited: proves the override alone is doing the work,
                # not some other ambient variable.
                "PATH": __import__("os").environ.get("PATH", ""),
                "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
                "PYTHONPATH": str(REPO_ROOT / "src"),
            },
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        assert result.returncode == 0, (
            f"subprocess failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        resolved = json.loads(result.stdout)

        not_under_override = {
            name: value
            for name, value in resolved.items()
            if not value.replace("\\", "/").startswith(override_root.replace("\\", "/"))
        }
        assert not not_under_override, (
            f"these resolved outside RECOMMENDER_DATA_ROOT ({override_root}), meaning they "
            f"are still built from a cwd-relative or otherwise unanchored path: {not_under_override}"
        )
