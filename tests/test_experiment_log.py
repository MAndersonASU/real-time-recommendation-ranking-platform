import os
import subprocess

from recommender.tracking.experiment_log import _current_git_commit, load_runs, log_run


def test_log_run_returns_a_record_with_a_real_git_commit(tmp_path):
    path = tmp_path / "log.jsonl"

    record = log_run("test_run", params={"k": 10}, metrics={"ndcg": 0.5}, path=path)

    assert record["run_name"] == "test_run"
    assert record["params"] == {"k": 10}
    assert record["metrics"] == {"ndcg": 0.5}
    # This repo is a real git checkout, so a real commit hash should
    # come back, not None -- confirms the subprocess call actually works,
    # not just that it doesn't raise.
    assert record["git_commit"] is not None
    assert len(record["git_commit"]) == 40


def test_load_runs_is_empty_before_anything_is_logged(tmp_path):
    path = tmp_path / "log.jsonl"

    assert load_runs(path=path).empty


def test_load_runs_flattens_params_and_metrics_into_columns(tmp_path):
    path = tmp_path / "log.jsonl"
    log_run("run_a", params={"k": 10}, metrics={"ndcg": 0.5, "hit_rate": 0.6}, path=path)
    log_run("run_b", params={"k": 10}, metrics={"ndcg": 0.4, "hit_rate": 0.55}, path=path)

    df = load_runs(path=path)

    assert list(df["run_name"]) == ["run_a", "run_b"]
    assert list(df["param_k"]) == [10, 10]
    assert list(df["metric_ndcg"]) == [0.5, 0.4]


def test_log_run_appends_rather_than_overwrites(tmp_path):
    path = tmp_path / "log.jsonl"
    log_run("first", params={}, metrics={"x": 1}, path=path)
    log_run("second", params={}, metrics={"x": 2}, path=path)

    df = load_runs(path=path)

    assert len(df) == 2
    assert set(df["run_name"]) == {"first", "second"}


def test_current_git_commit_resolves_this_projects_repo_even_from_a_different_cwd(tmp_path):
    """Regression test for a real bug, found by audit: `git rev-parse
    HEAD` with no explicit `cwd` resolves relative to the *process's*
    current working directory, not this project's own location. Calling
    it from inside a completely different git repository previously
    returned that other repo's commit -- silently wrong reproducibility
    identity -- rather than this project's own. Fails on the pre-fix
    code (returns the other repo's commit) and passes once the git
    command is anchored to this file's own location via `cwd=`.
    """
    real_commit = _current_git_commit()
    assert real_commit is not None  # this repo is a real git checkout

    other_repo = tmp_path / "unrelated_repo"
    other_repo.mkdir()
    subprocess.run(["git", "init"], cwd=other_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=other_repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=other_repo, check=True)
    (other_repo / "file.txt").write_text("content")
    subprocess.run(["git", "add", "file.txt"], cwd=other_repo, check=True)
    subprocess.run(["git", "commit", "-m", "unrelated commit"], cwd=other_repo, check=True, capture_output=True)

    original_cwd = os.getcwd()
    os.chdir(other_repo)
    try:
        commit_from_elsewhere = _current_git_commit()
    finally:
        os.chdir(original_cwd)

    assert commit_from_elsewhere == real_commit


def test_current_git_commit_prefers_the_git_commit_sha_environment_variable():
    """Regression test for a real gap, found by a follow-up audit:
    repository discovery is a real fallback for local development, but
    a container image built with no .git directory at all (the
    Dockerfile only copies pyproject.toml and src/) would always
    resolve to None there. GIT_COMMIT_SHA, when set, must take priority
    over discovering it from a local .git directory.
    """
    original = os.environ.get("GIT_COMMIT_SHA")
    os.environ["GIT_COMMIT_SHA"] = "deadbeef-a-real-env-supplied-commit-identity"
    try:
        assert _current_git_commit() == "deadbeef-a-real-env-supplied-commit-identity"
    finally:
        if original is None:
            os.environ.pop("GIT_COMMIT_SHA", None)
        else:
            os.environ["GIT_COMMIT_SHA"] = original


def test_current_git_commit_falls_back_to_repository_discovery_when_env_var_is_unset():
    original = os.environ.pop("GIT_COMMIT_SHA", None)
    try:
        real_commit = _current_git_commit()
        assert real_commit is not None
        assert len(real_commit) == 40  # a real git commit hash, not the env-var literal
    finally:
        if original is not None:
            os.environ["GIT_COMMIT_SHA"] = original
