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


def test_build_demo_data_reports_the_real_retrieval_history_source():
    """SERVING-DURABLE-HISTORY-69: the demo must report which history
    actually drove retrieval, not just whether some feature lookup
    found a record. u1 has a real durable history and no recent Redis
    record in this fixture context, so retrieval must report "durable",
    not merely repeat the older durable_features_used flag.
    """
    context = _build_context()

    data = build_demo_data("u1", context, num_candidates=2, news_by_id=NEWS_BY_ID)

    assert data["retrieval_history_source"] == "durable"


def test_render_demo_html_distinguishes_durable_from_recent_from_global_popularity():
    """The three retrieval sources must render as three genuinely
    different, distinguishable labels -- not the same "Partially
    personalized" phrase collapsing a durable-history retrieval and a
    global-popularity one into indistinguishable text, which overstated
    how personalized a global-popularity slate actually was.
    """
    from recommender.features.online_features import RecentUserFeatures
    from recommender.features.state_store import save_recent_features
    from tests.test_pipeline import _FakeRedis

    durable_only_context = _build_context()
    durable_html = render_demo_html("u1", durable_only_context, num_candidates=2, news_by_id=NEWS_BY_ID)

    redis_client = _FakeRedis()
    save_recent_features(
        redis_client,
        RecentUserFeatures(
            user_id="u1", recent_clicked_items=["n1", "n2"],
            impressions_seen=2, clicks_seen=2, last_event_time=None,
        ),
    )
    recent_context = _build_context(redis_client=redis_client)
    recent_html = render_demo_html("u1", recent_context, num_candidates=2, news_by_id=NEWS_BY_ID)

    global_popularity_html = render_demo_html(
        "a-user-nobody-has-ever-seen", durable_only_context, num_candidates=2, news_by_id=NEWS_BY_ID
    )

    assert "Durable-history retrieval" in durable_html
    assert "Recent-history retrieval" in recent_html
    assert "Global-popularity retrieval" in global_popularity_html
    # All three must actually differ -- not just present, but distinct.
    assert len({durable_html, recent_html, global_popularity_html}) == 3
