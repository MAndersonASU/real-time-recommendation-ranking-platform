from recommender.monitoring.load_test import run_load_test, sweep_concurrency
from tests.test_pipeline import _build_context


def test_run_load_test_reports_the_real_requested_count():
    context = _build_context()

    report = run_load_test(context, user_ids=["u1", "u2"], concurrency=2, num_requests=10)

    assert report["requests"] == 10
    assert report["error_rate"] == 0.0
    assert report["throughput_rps"] > 0


def test_run_load_test_percentiles_are_ordered_and_non_negative():
    context = _build_context()

    report = run_load_test(context, user_ids=["u1", "u2"], concurrency=4, num_requests=20)

    assert 0.0 <= report["p50_ms"] <= report["p95_ms"] <= report["p99_ms"]


def test_sweep_concurrency_runs_one_report_per_level():
    context = _build_context()

    reports = sweep_concurrency(
        context, user_ids=["u1", "u2"], concurrency_levels=(1, 2, 4), requests_per_level=6
    )

    assert [r["concurrency"] for r in reports] == [1, 2, 4]
    assert all(r["requests"] == 6 for r in reports)
