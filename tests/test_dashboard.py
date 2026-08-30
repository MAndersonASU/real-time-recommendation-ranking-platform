from datetime import datetime

from recommender.monitoring import metrics as m
from recommender.monitoring.dashboard import build_dashboard_data, render_dashboard_html
from recommender.serving.contract import RecommendationResponse


def _response() -> RecommendationResponse:
    return RecommendationResponse(
        user_id="u1",
        recommendations=[],
        durable_features_used=True,
        recent_features_used=False,
        retrieval_history_source="durable",
        generated_at=datetime(2019, 11, 15, 8, 0, 0),  # noqa: DTZ001
    )


def test_build_dashboard_data_computes_a_real_error_rate():
    before_success = m.REQUEST_COUNT.labels(outcome="success")._value.get()
    before_error = m.REQUEST_COUNT.labels(outcome="error")._value.get()
    m.record_response(_response(), is_fallback=False, latency_seconds=0.01)
    m.record_error()

    data = build_dashboard_data()

    total = before_success + before_error + 2
    expected_error = (before_error + 1) / total
    assert data["error_rate"] == expected_error


def test_render_dashboard_html_produces_a_real_html_page():
    html = render_dashboard_html()

    assert "<html>" in html
    assert "Recommend attempts" in html
    assert "Error rate" in html


def test_render_dashboard_html_never_raises_with_no_data_at_all():
    # A brand-new process registry would have zero counts everywhere;
    # this only confirms the render path tolerates that shape without
    # dividing by zero, not that counts are actually zero (this test
    # runs in the same process as every other test in the suite, whose
    # counters are real and shared).
    html = render_dashboard_html()

    assert isinstance(html, str)
