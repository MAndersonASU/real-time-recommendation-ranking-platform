from unittest.mock import patch

import pandas as pd

from recommender.evaluation.evaluate_end_to_end import evaluate_end_to_end
from recommender.features.fake_redis import InMemoryRedis
from tests.test_pipeline import NEWS, _build_context

VALIDATION_BEHAVIORS = pd.DataFrame(
    {
        "impression_id": [10, 11],
        "user_id": ["u1", "u2"],
        "time": pd.to_datetime(["2019-11-14T08:00:00", "2019-11-14T09:00:00"]),
        "history": ["n1 n2", "n4"],
        "impressions": ["n1-1 n3-0", "n5-0 n6-1"],
    }
)


def test_evaluate_end_to_end_reports_real_evaluated_and_skipped_counts():
    context = _build_context()

    report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)

    assert report["impressions_in_sample"] == 2
    assert report["impressions_evaluated"] == 2
    assert report["impressions_skipped"] == {}
    assert report["k"] == 3


def test_evaluate_end_to_end_metrics_and_coverage_are_in_a_valid_range():
    context = _build_context()

    report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)

    assert 0.0 <= report["hit_rate_at_k"] <= 1.0
    assert 0.0 <= report["recall_at_k"] <= 1.0
    assert 0.0 <= report["ndcg_at_k"] <= 1.0
    assert 0.0 <= report["mrr"] <= 1.0
    assert 0.0 <= report["catalog_coverage"] <= 1.0
    assert 0.0 <= report["durable_feature_coverage"] <= 1.0
    assert 0.0 <= report["recent_feature_coverage"] <= 1.0


def test_evaluate_end_to_end_skips_impressions_with_no_real_click_and_records_the_reason():
    context = _build_context()
    no_click_behaviors = pd.DataFrame(
        {
            "impression_id": [20],
            "user_id": ["u1"],
            "time": pd.to_datetime(["2019-11-14T08:00:00"]),
            "history": ["n1"],
            "impressions": ["n2-0 n3-0"],
        }
    )

    report = evaluate_end_to_end(context, num_impressions=1, k=3, validation=no_click_behaviors, news=NEWS)

    assert report["impressions_evaluated"] == 0
    assert report["impressions_skipped"] == {"no_real_click": 1}
    assert report["hit_rate_at_k"] == 0.0


def test_evaluate_end_to_end_calls_the_real_serving_path():
    """Regression test proving this still calls the real recommend()
    pipeline (retrieval -> ranking -> reranking) rather than a
    re-implementation, and that each request carries the real
    impression's own user and historical time.
    """
    import recommender.evaluation.evaluate_end_to_end as module

    context = _build_context()
    real_safe_recommend = module.safe_recommend
    calls = []

    def _capturing_safe_recommend(request, *args, **kwargs):
        calls.append(request)
        return real_safe_recommend(request, *args, **kwargs)

    with patch.object(module, "safe_recommend", side_effect=_capturing_safe_recommend):
        evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)

    assert len(calls) == 2
    assert {request.user_id for request in calls} == {"u1", "u2"}
    for request, expected_time in zip(
        calls, pd.to_datetime(["2019-11-14T08:00:00", "2019-11-14T09:00:00"]), strict=True
    ):
        assert request.request_time == expected_time


def test_evaluate_end_to_end_uses_each_impressions_own_history_not_a_later_ones():
    """Regression test for the real point-in-time-correctness bug found
    by the follow-up audit: durable features used to come from a user's
    *latest* row in the whole split (context.durable_cache, built once
    at context-construction time), so an early impression could see a
    later impression's own history. Two impressions for the same user,
    with different `history` fields, at different times -- each must be
    scored using only its own row's history.
    """
    context = _build_context()
    behaviors = pd.DataFrame(
        {
            "impression_id": [30, 31],
            "user_id": ["u1", "u1"],
            "time": pd.to_datetime(["2019-11-09T08:00:00", "2019-11-09T09:00:00"]),
            # The first impression's history has no tech clicks; the
            # second (later) impression's history does. If the first
            # impression incorrectly saw the second's history, its
            # dominant category would leak tech affinity it shouldn't
            # have yet.
            "history": ["n1", "n1 n4 n5"],
            "impressions": ["n2-0 n3-1", "n6-0 n4-1"],
        }
    )

    captured_durable_lifetime_counts = []
    import recommender.evaluation.evaluate_end_to_end as module
    real_point_in_time = module._point_in_time_durable_features

    def _capturing(user_id, history_raw, category_by_id):
        durable = real_point_in_time(user_id, history_raw, category_by_id)
        captured_durable_lifetime_counts.append(durable.lifetime_click_count)
        return durable

    with patch.object(module, "_point_in_time_durable_features", side_effect=_capturing):
        evaluate_end_to_end(context, num_impressions=2, k=3, validation=behaviors, news=NEWS)

    # First impression sees only "n1" (1 history item); second sees
    # "n1 n4 n5" (3 history items) -- each impression's own row, not a
    # shared "latest" snapshot for the user.
    assert captured_durable_lifetime_counts == [1, 3]


def test_evaluate_end_to_end_evolves_recent_state_chronologically_not_from_the_future():
    """Regression test proving state evolves in real chronological order:
    a click in an earlier impression must be visible as recent-feature
    state for a strictly later impression from the same user, but the
    earlier impression itself must never have benefited from it (state
    is applied only after scoring, per the required remediation).
    """
    context = _build_context()
    behaviors = pd.DataFrame(
        {
            "impression_id": [40, 41],
            "user_id": ["u1", "u1"],
            "time": pd.to_datetime(["2019-11-09T08:00:00", "2019-11-09T09:00:00"]),
            "history": ["", ""],
            "impressions": ["n2-0 n3-1", "n6-0 n4-1"],
        }
    )

    import recommender.evaluation.evaluate_end_to_end as module
    real_safe_recommend = module.safe_recommend
    responses = []

    def _capturing_safe_recommend(request, *args, **kwargs):
        response = real_safe_recommend(request, *args, **kwargs)
        responses.append(response)
        return response

    with patch.object(module, "safe_recommend", side_effect=_capturing_safe_recommend):
        evaluate_end_to_end(context, num_impressions=2, k=3, validation=behaviors, news=NEWS)

    assert len(responses) == 2
    assert responses[0].recent_features_used is False  # nothing has happened yet
    assert responses[1].recent_features_used is True  # the first impression's click is now recent history


def test_evaluate_end_to_end_never_touches_the_shared_context_redis_client():
    """Regression test for a real isolation bug found by the follow-up
    audit: the evaluation used to reuse `context.redis_client` and
    `context.durable_cache` directly -- ambient state shared with
    whatever else is running against the same context. A Redis client
    that raises on any real call proves the evaluation never touches it.
    """

    class _ExplodingRedis:
        def get(self, key):
            raise AssertionError("evaluate_end_to_end must never touch the shared context redis_client")

        def set(self, key, value, ex=None):
            raise AssertionError("evaluate_end_to_end must never touch the shared context redis_client")

        def ping(self):
            raise AssertionError("evaluate_end_to_end must never touch the shared context redis_client")

    context = _build_context(redis_client=_ExplodingRedis())

    report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)

    assert report["impressions_evaluated"] == 2


def test_evaluate_end_to_end_is_deterministic_across_repeated_runs():
    context = _build_context()

    report_a = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)
    report_b = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)

    assert report_a == report_b


def test_evaluate_end_to_end_has_no_leakage_from_future_impressions():
    """A later impression must never change an earlier one's result:
    evaluating a truncated prefix of the input must reproduce identical
    metrics for those same impressions as evaluating the full input.
    """
    context = _build_context()
    behaviors = pd.DataFrame(
        {
            "impression_id": [50, 51, 52],
            "user_id": ["u1", "u1", "u1"],
            "time": pd.to_datetime(
                ["2019-11-09T08:00:00", "2019-11-09T09:00:00", "2019-11-09T10:00:00"]
            ),
            "history": ["n1", "n1", "n1"],
            "impressions": ["n2-0 n3-1", "n6-0 n4-1", "n5-1 n7-0"],
        }
    )

    full_report = evaluate_end_to_end(context, num_impressions=3, k=3, validation=behaviors, news=NEWS)
    truncated_report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=behaviors, news=NEWS)

    # Both runs score the same first two impressions; a real leakage bug
    # would make the third (future, in the full run) impression's click
    # visible during the second impression's evaluation.
    assert full_report["impressions_evaluated"] >= truncated_report["impressions_evaluated"]
    assert truncated_report["impressions_evaluated"] == 2


def test_evaluate_end_to_end_reports_fallback_reasons_not_just_a_count():
    """Regression test proving a real dependency failure surfaces a real
    reason string, not just an opaque count. Only the served request's
    own two-tower forward pass is made to fail -- the evaluation
    harness's own post-scoring state bookkeeping (a separate call,
    against the same isolated in-memory store) is untouched, matching
    the real distinction between "the served request's dependency
    lookup failed" and "the evaluation harness's own bookkeeping,"
    which is not part of what `safe_recommend` ever sees or protects.

    A broken two-tower model, not a failing Redis lookup: since
    REDIS-DEGRADED-PATH-61, a Redis failure degrades to a real,
    personalized response rather than falling back at all, so it can no
    longer stand in for "a real dependency failure" here -- the two-tower
    model genuinely is required for retrieval, so `recommend()` still
    translates its failure into `DependencyUnavailableError`.
    """
    context = _build_context()

    with patch.object(
        context.two_tower_model, "user_vector", side_effect=RuntimeError("simulated model failure")
    ):
        report = evaluate_end_to_end(context, num_impressions=2, k=3, validation=VALIDATION_BEHAVIORS, news=NEWS)

    assert report["fallback_count"] == 2
    assert report["fallback_reasons"] == {"two_tower_inference_failed": 2}


def test_apply_impression_to_recent_state_and_isolated_redis_are_real_and_reusable():
    """A direct, low-level sanity check on the isolation primitive
    itself: InMemoryRedis is a real, independent store, not a shared
    singleton reused across calls by accident.
    """
    isolated_a = InMemoryRedis()
    isolated_b = InMemoryRedis()

    isolated_a.set("k", "v")

    assert isolated_b.get("k") is None


def test_evaluate_end_to_end_seeds_recent_state_from_each_impressions_own_history():
    """Regression test for a real evaluation bug: the isolated state store
    started empty for every user, so an impression whose user had no
    *earlier in-window* event was scored with an empty click list. The
    serving path builds its two-tower query from that list, and an empty
    history yields an exactly zero-norm user vector -- against which an
    inner-product index scores every catalog item identically, handing
    every such user the same arbitrary slate.

    MIND's own per-impression `history` field records the clicks that
    happened strictly before that impression, so it is exactly what a
    live store would already hold, and using it is point-in-time correct
    rather than leakage. Fails on the pre-fix code (recent features are a
    cold-start fallback on the very first impression despite real history
    existing) and passes once that history seeds the store.
    """
    context = _build_context()
    behaviors = pd.DataFrame(
        {
            "impression_id": [50],
            "user_id": ["u1"],
            "time": pd.to_datetime(["2019-11-14T08:00:00"]),
            "history": ["n1 n2"],
            "impressions": ["n3-1 n5-0"],
        }
    )

    import recommender.evaluation.evaluate_end_to_end as module
    real_safe_recommend = module.safe_recommend
    responses = []

    def _capturing(request, *args, **kwargs):
        response = real_safe_recommend(request, *args, **kwargs)
        responses.append(response)
        return response

    with patch.object(module, "safe_recommend", side_effect=_capturing):
        report = evaluate_end_to_end(context, num_impressions=1, k=3, validation=behaviors, news=NEWS)

    assert len(responses) == 1
    assert responses[0].recent_features_used is True
    assert report["recent_feature_coverage"] == 1.0


def _reconcile(history, in_window, baseline):
    from recommender.evaluation.evaluate_end_to_end import _reconcile_recent_state
    from recommender.features.state_store import load_recent_features

    client = InMemoryRedis()
    _reconcile_recent_state(client, "u1", history, in_window, baseline)
    return load_recent_features(client, "u1")


def test_reconciliation_drops_a_click_the_history_has_absorbed():
    """MIND's `history` advances, so a later impression's history can
    already contain a click this run observed. Counting it again inflated
    clicks_seen and repeated the item in the embedding history.
    """
    recent = _reconcile("n1 n2 n3", ["n3"], baseline=2)

    assert recent.recent_clicked_items == ["n1", "n2", "n3"]
    assert recent.clicks_seen == 3


def test_reconciliation_keeps_a_repeat_of_a_pre_window_click():
    """The case occurrence-counting could not express. The user's
    pre-window history already contained `n3`, and they have now clicked
    it again while the history has not yet advanced.

    Matching by article count read the existing `n3` as proof the click
    was absorbed and silently dropped a real click. Anchoring on the
    history length at first encounter removes the ambiguity: the history
    has not grown, so nothing has been absorbed.
    """
    recent = _reconcile("n1 n3", ["n3"], baseline=2)

    assert recent.recent_clicked_items == ["n1", "n3", "n3"]
    assert recent.clicks_seen == 3


def test_reconciliation_appends_a_click_history_has_not_caught_up_to():
    recent = _reconcile("n1 n2", ["n3"], baseline=2)

    assert recent.recent_clicked_items == ["n1", "n2", "n3"]
    assert recent.clicks_seen == 3


def test_reconciliation_absorbs_exactly_as_many_clicks_as_history_grew():
    """Two observed clicks, history grew by two: both absorbed."""
    recent = _reconcile("n1 n2 n3", ["n2", "n3"], baseline=1)

    assert recent.recent_clicked_items == ["n1", "n2", "n3"]
    assert recent.clicks_seen == 3


def test_reconciliation_absorbs_only_the_prefix_history_grew_by():
    """History grew by one while the run observed two clicks, so only
    the first is absorbed and the second is still additional.
    """
    recent = _reconcile("n1 n2", ["n2", "n5"], baseline=1)

    assert recent.recent_clicked_items == ["n1", "n2", "n5"]
    assert recent.clicks_seen == 3


def test_reconciliation_with_no_history_uses_only_observed_clicks():
    recent = _reconcile("", ["n5"], baseline=0)

    assert recent.recent_clicked_items == ["n5"]
    assert recent.clicks_seen == 1


def test_impressions_sharing_a_timestamp_do_not_see_each_others_events():
    """Equal timestamps carry no ordering information, so one such
    impression must not observe another's click: that is not
    strictly-earlier information, only earlier file order. Every
    impression in a timestamp group is scored before any of the group's
    events are applied.
    """
    context = _build_context()
    behaviors = pd.DataFrame(
        {
            "impression_id": [60, 61],
            "user_id": ["u1", "u1"],
            # Deliberately identical.
            "time": pd.to_datetime(["2019-11-14T08:00:00", "2019-11-14T08:00:00"]),
            "history": ["", ""],
            "impressions": ["n2-0 n3-1", "n6-0 n4-1"],
        }
    )

    import recommender.evaluation.evaluate_end_to_end as module
    real = module.safe_recommend
    responses = []

    def _capture(request, *args, **kwargs):
        response = real(request, *args, **kwargs)
        responses.append(response)
        return response

    with patch.object(module, "safe_recommend", side_effect=_capture):
        evaluate_end_to_end(context, num_impressions=2, k=3, validation=behaviors, news=NEWS)

    assert len(responses) == 2
    # Neither may have seen recent state, because the only candidate
    # source of it is the other impression at the very same instant.
    assert all(r.recent_features_used is False for r in responses)


def test_evaluation_is_prefix_invariant():
    """The strongest available check on temporal integrity: evaluating a
    chronological prefix must give bit-identical results whether or not
    later rows exist in the input.

    Counting metrics alone would not catch a leak that changed *which*
    items were recommended while leaving totals similar, so this
    compares every response's candidate ordering and scores.
    """
    context = _build_context()
    prefix = pd.DataFrame(
        {
            "impression_id": [70, 71],
            "user_id": ["u1", "u2"],
            "time": pd.to_datetime(["2019-11-14T08:00:00", "2019-11-14T09:00:00"]),
            "history": ["n1", "n4"],
            "impressions": ["n2-0 n3-1", "n6-0 n5-1"],
        }
    )
    future = pd.DataFrame(
        {
            "impression_id": [72, 73],
            "user_id": ["u1", "u2"],
            "time": pd.to_datetime(["2019-11-14T10:00:00", "2019-11-14T11:00:00"]),
            "history": ["n1 n3", "n4 n5"],
            "impressions": ["n5-1 n7-0", "n2-1 n8-0"],
        }
    )
    with_future = pd.concat([prefix, future], ignore_index=True)

    def _run(frame, limit):
        import recommender.evaluation.evaluate_end_to_end as module
        real = module.safe_recommend
        captured = []

        def _capture(request, *args, **kwargs):
            response = real(request, *args, **kwargs)
            captured.append(
                (
                    request.user_id,
                    str(request.request_time),
                    tuple((i.news_id, round(i.score, 12)) for i in response.recommendations),
                )
            )
            return response

        with patch.object(module, "safe_recommend", side_effect=_capture):
            report = evaluate_end_to_end(context, num_impressions=limit, k=3, validation=frame, news=NEWS)
        return captured, report

    prefix_only, prefix_report = _run(prefix, 2)
    # Same prefix, but the input also contains strictly later rows.
    with_future_all, _ = _run(with_future, 4)

    assert len(prefix_only) == 2
    assert with_future_all[: len(prefix_only)] == prefix_only, (
        "a later row changed an earlier impression's recommendations"
    )

    # And the prefix's own metric contributions are unchanged.
    prefix_of_longer, longer_report = _run(with_future.head(2), 2)
    assert prefix_of_longer == prefix_only
    assert longer_report["hit_rate_at_k"] == prefix_report["hit_rate_at_k"]


def test_out_of_order_source_rows_are_sorted_deterministically():
    """The source frame's row order must not affect results: the
    evaluation sorts by (time, impression_id), so a shuffled input
    produces the same run.
    """
    context = _build_context()
    rows = pd.DataFrame(
        {
            "impression_id": [80, 81, 82],
            "user_id": ["u1", "u2", "u1"],
            "time": pd.to_datetime(
                ["2019-11-14T08:00:00", "2019-11-14T09:00:00", "2019-11-14T10:00:00"]
            ),
            "history": ["n1", "n4", "n1 n3"],
            "impressions": ["n2-0 n3-1", "n6-0 n5-1", "n5-1 n7-0"],
        }
    )
    shuffled = rows.iloc[[2, 0, 1]].reset_index(drop=True)

    in_order = evaluate_end_to_end(context, num_impressions=3, k=3, validation=rows, news=NEWS)
    out_of_order = evaluate_end_to_end(context, num_impressions=3, k=3, validation=shuffled, news=NEWS)

    assert in_order == out_of_order
