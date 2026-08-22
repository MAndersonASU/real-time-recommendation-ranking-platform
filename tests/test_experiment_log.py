from recommender.tracking.experiment_log import load_runs, log_run


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
