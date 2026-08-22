from recommender.serving.demo import build_demo_data, render_demo_html
from tests.test_pipeline import NEWS, _build_context

NEWS_BY_ID = NEWS.set_index("news_id")


def test_build_demo_data_returns_the_requested_number_of_items():
    context = _build_context()

    data = build_demo_data("u1", context, num_candidates=3, news_by_id=NEWS_BY_ID)

    assert len(data["items"]) == 3


def test_build_demo_data_reports_stage_timings_for_every_real_stage():
    context = _build_context()

    data = build_demo_data("u1", context, num_candidates=2, news_by_id=NEWS_BY_ID)

    assert set(data["stage_timings_ms"].keys()) == {
        "feature_lookup_ms", "embedding_ms", "retrieval_ms",
        "feature_build_ms", "ranking_ms", "reranking_ms",
    }
    assert data["total_ms"] > 0


def test_build_demo_data_looks_up_real_titles_from_the_catalog():
    context = _build_context()

    data = build_demo_data("u2", context, num_candidates=4, news_by_id=NEWS_BY_ID)

    real_titles = set(NEWS["title"])
    assert all(item["title"] in real_titles for item in data["items"])


def test_build_demo_data_flags_a_fully_unknown_user_as_not_personalized():
    context = _build_context()

    data = build_demo_data(
        "a-user-nobody-has-ever-seen", context, num_candidates=2, news_by_id=NEWS_BY_ID
    )

    assert data["durable_features_used"] is False
    assert data["recent_features_used"] is False


def test_render_demo_html_includes_the_user_id_and_a_real_title():
    context = _build_context()

    html = render_demo_html("u1", context, num_candidates=2, news_by_id=NEWS_BY_ID)

    assert "u1" in html
    assert "<html>" in html.lower()
    assert any(title in html for title in NEWS["title"])
