from datetime import UTC

import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from recommender.features.online_features import RecentUserFeatures
from recommender.features.state_store import save_recent_features
from recommender.ranking.baselines import build_content_vectors, compute_popularity
from recommender.ranking.train import MODEL_FEATURE_COLUMNS
from recommender.reranking.freshness import compute_age_days, compute_first_seen
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_item_content_matrix,
    build_item_vocab,
)
from recommender.retrieval.index import build_exact_index, compute_catalog_embeddings
from recommender.retrieval.model import TwoTowerModel
from recommender.serving.cache import build_durable_feature_cache
from recommender.serving.contract import RecommendationRequest
from recommender.serving.pipeline import ServingContext, recommend

NEWS = pd.DataFrame(
    {
        "news_id": [f"n{i}" for i in range(1, 9)],
        "category": ["sports", "sports", "sports", "tech", "tech", "tech", "news", "news"],
        "subcategory": ["football", "football", "tennis", "gadgets", "ai", "ai", "world", "local"],
        "title": [
            "team wins big game", "striker scores twice", "tennis final result",
            "new phone released", "ai model breakthrough", "ai research lab opens",
            "world summit begins", "local council meets",
        ],
        "abstract": [""] * 8,
    }
)

TRAIN_BEHAVIORS = pd.DataFrame(
    {
        "impression_id": [1, 2],
        "user_id": ["u1", "u2"],
        "time": pd.to_datetime(["2019-11-09T08:00:00", "2019-11-09T09:00:00"]),
        "history": ["n1 n2", "n4"],
        "impressions": ["n3-0 n1-1", "n5-1 n6-0"],
    }
)


class _FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)

    def ping(self):
        return True


def _build_context(redis_client=None) -> ServingContext:
    item_vocab, categories, subcategories = build_item_vocab(NEWS)
    catalog_cat, catalog_subcat, item_row_by_news_id = build_catalog_arrays(NEWS, item_vocab)
    item_content = build_item_content_matrix(NEWS)

    model = TwoTowerModel(len(categories) + 1, len(subcategories) + 1, embedding_dim=8)
    model.eval()
    catalog_embeddings = compute_catalog_embeddings(
        model, catalog_cat, catalog_subcat, item_content
    )
    faiss_index = build_exact_index(catalog_embeddings)

    tfidf_vectors, tfidf_row_by_id = build_content_vectors(NEWS)

    # A tiny, real, fitted ranking model -- not a mock -- trained on
    # synthetic rows with the same five columns and column order the real
    # model uses, just enough data for LogisticRegression to fit both
    # classes without error.
    synthetic = pd.DataFrame(
        {
            "retrieval_score": [0.1, 0.5, 0.9, 0.2, 0.6, 0.8],
            "category_match": [0.0, 1.0, 1.0, 0.0, 1.0, 0.0],
            "content_similarity": [0.0, 0.3, 0.7, 0.1, 0.4, 0.2],
            "user_history_length": [1, 3, 5, 2, 4, 1],
            "hour_of_day": [8, 8, 9, 10, 11, 12],
            "clicked": [0, 0, 1, 0, 1, 1],
        }
    )
    ranking_model = Pipeline([("scale", StandardScaler()), ("logreg", LogisticRegression())])
    # .to_numpy(), matching train.py's real fit convention -- serving
    # calls predict_proba on a plain array too, and a names/no-names
    # mismatch between fit and predict triggers a real sklearn warning.
    ranking_model.fit(synthetic[MODEL_FEATURE_COLUMNS].to_numpy(), synthetic["clicked"])

    durable_cache = build_durable_feature_cache(TRAIN_BEHAVIORS, NEWS)
    first_seen = compute_first_seen(TRAIN_BEHAVIORS)

    return ServingContext(
        item_vocab=item_vocab,
        item_content=item_content,
        item_row_by_news_id=item_row_by_news_id,
        news_ids=NEWS["news_id"].to_numpy(),
        category_by_id=NEWS.set_index("news_id")["category"],
        tfidf_vectors=tfidf_vectors,
        tfidf_row_by_id=tfidf_row_by_id,
        faiss_index=faiss_index,
        two_tower_model=model,
        ranking_model=ranking_model,
        durable_cache=durable_cache,
        first_seen=first_seen,
        popularity=compute_popularity(TRAIN_BEHAVIORS),
        redis_client=redis_client if redis_client is not None else _FakeRedis(),
    )


def test_recommend_returns_exactly_the_requested_number_of_items():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=5)

    response = recommend(request, context)

    assert len(response.recommendations) == 5


def test_recommend_ranks_are_sequential_starting_at_one():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=4)

    response = recommend(request, context)

    assert [item.rank for item in response.recommendations] == [1, 2, 3, 4]


def test_recommend_flags_a_fully_unknown_user_as_not_personalized():
    context = _build_context()
    request = RecommendationRequest(user_id="a-user-nobody-has-ever-seen", num_candidates=3)

    response = recommend(request, context)

    assert response.durable_features_used is False
    assert response.recent_features_used is False


def test_recommend_flags_a_fully_known_user_as_personalized():
    context = _build_context()
    save_recent_features(
        context.redis_client,
        RecentUserFeatures(
            user_id="u1", recent_clicked_items=["n1", "n2"], impressions_seen=3,
            clicks_seen=2, last_event_time="2019-11-09T09:00:00",
        ),
    )
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    response = recommend(request, context)

    assert response.durable_features_used is True
    assert response.recent_features_used is True


def test_recommend_recommendations_are_real_catalog_items():
    context = _build_context()
    request = RecommendationRequest(user_id="u2", num_candidates=4)

    response = recommend(request, context)

    catalog_ids = set(NEWS["news_id"])
    assert all(item.news_id in catalog_ids for item in response.recommendations)


def test_recommend_leaves_matched_signals_none_by_default():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    response = recommend(request, context)

    assert response.matched_signals is None


def test_recommend_populates_matched_signals_when_opted_in():
    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    response = recommend(request, context, include_matched_signals=True)

    assert response.matched_signals is not None
    assert set(response.matched_signals.keys()) == {item.news_id for item in response.recommendations}
    for signals in response.matched_signals.values():
        assert isinstance(signals.category_match, bool)
        assert isinstance(signals.content_similarity, float)
        assert isinstance(signals.retrieval_score, float)
        assert signals.user_history_length >= 0


def test_recommend_falls_back_to_a_real_utc_clock_not_local_wall_clock_time():
    """Regression test for a real bug, found by a follow-up audit: when
    no request_time is given (e.g. every /demo request), this used to
    fall back to the bare local-wall-clock datetime.now() -- on a server
    whose OS timezone isn't UTC, silently inconsistent with every other
    naive-but-UTC-by-convention timestamp in this project. Fails on the
    pre-fix code (datetime.now() called with no timezone argument at
    all) and passes once it's called with timezone.utc explicitly.
    """
    from unittest.mock import patch

    import recommender.serving.pipeline as pipeline_module

    context = _build_context()
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    with patch.object(pipeline_module, "datetime", wraps=pipeline_module.datetime) as mock_datetime:
        recommend(request, context)

    now_calls = [call for call in mock_datetime.now.call_args_list]
    assert now_calls, "expected datetime.now() to be called at least once"
    for call in now_calls:
        args, kwargs = call
        tz_arg = args[0] if args else kwargs.get("tz")
        assert tz_arg is UTC


def test_recommend_skips_freshness_reranking_without_a_real_request_time():
    """Regression test for a real bug, found by a follow-up audit: MIND
    is a frozen November 2019 dataset, so comparing it against the real
    wall clock makes every known item look thousands of days old --
    "freshness relative to right now" has no real meaning for a request
    that never said what "now" should be relative to the dataset. Fails
    on the pre-fix code (freshness reranking always ran, even with no
    real historical grounding) and passes once it's skipped unless a
    real request_time was actually supplied.
    """
    from unittest.mock import patch

    import recommender.serving.pipeline as pipeline_module

    context = _build_context()
    no_time_request = RecommendationRequest(user_id="u1", num_candidates=3)
    with_time_request = RecommendationRequest(
        user_id="u1", num_candidates=3, request_time=pd.Timestamp("2019-11-09T10:00:00")
    )

    with patch.object(pipeline_module, "apply_freshness_quota") as mock_quota:
        recommend(no_time_request, context)
        assert mock_quota.call_count == 0

        mock_quota.side_effect = lambda slate, *a, **k: slate  # pass through unchanged
        recommend(with_time_request, context)
        assert mock_quota.call_count == 1


def test_recommend_does_not_query_faiss_with_a_zero_vector_for_a_history_less_user():
    """Regression test for a real serving bug: `user_vector` averages the
    item vectors of a user's click history, so a user with no usable
    history yields an exactly zero-norm embedding. An inner-product index
    scores every catalog item 0.0 against a zero query, so Faiss returned
    an arbitrary tie order -- the identical slate for every history-less
    user, with a constant retrieval_score giving every candidate the same
    ranking probability. Fails on the pre-fix code (Faiss is queried, and
    every returned score is identical) and passes once cold-start
    retrieval uses popularity, which is real signal here.
    """
    from unittest.mock import patch

    context = _build_context()
    request = RecommendationRequest(user_id="never-seen-before", num_candidates=3)

    with patch.object(context.faiss_index, "search", wraps=context.faiss_index.search) as spy:
        response = recommend(request, context)

    assert spy.call_count == 0, "a zero-norm query carries no signal; Faiss must not be asked"
    assert len(response.recommendations) == 3
    # The real symptom of the bug: every candidate scoring identically,
    # because retrieval_score was constant across a zero-vector search.
    scores = [item.score for item in response.recommendations]
    assert len(set(scores)) > 1, f"expected candidates to be distinguishable, got {scores}"
    # The most-clicked training item must be reachable through this path.
    most_popular = context.popularity.sort_values(ascending=False).index[0]
    assert most_popular in {item.news_id for item in response.recommendations}


def test_recommend_still_uses_faiss_when_the_user_has_real_history():
    """The cold-start popularity path above must not swallow the normal
    case: a user with real recent clicks produces a non-zero embedding
    and must still be served by real retrieval.
    """
    from unittest.mock import patch

    redis_client = _FakeRedis()
    save_recent_features(
        redis_client,
        RecentUserFeatures(
            user_id="u1", recent_clicked_items=["n1", "n2"],
            impressions_seen=2, clicks_seen=2, last_event_time=None,
        ),
    )
    context = _build_context(redis_client=redis_client)
    request = RecommendationRequest(user_id="u1", num_candidates=3)

    with patch.object(context.faiss_index, "search", wraps=context.faiss_index.search) as spy:
        recommend(request, context)

    assert spy.call_count == 1


def test_utc_clock_is_invariant_to_the_process_timezone():
    """Named for what it actually proves: reading the clock as UTC gives
    the same instant regardless of the process timezone.

    This is *not* a DST-transition test -- an earlier version of it was
    described as one, which overstated it. The real DST-boundary
    behaviour is covered by the two tests below. POSIX-only, because
    changing the process timezone at runtime needs `time.tzset`, which
    Windows does not provide; the DST tests below are portable and carry
    the substantive coverage.
    """
    import os
    import time as time_module
    from datetime import datetime

    if not hasattr(time_module, "tzset"):
        pytest.skip("time.tzset is POSIX-only; the DST-boundary tests below are portable")

    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "US/Eastern"
        time_module.tzset()
        before = datetime.now(UTC)
        os.environ["TZ"] = "UTC"
        time_module.tzset()
        after = datetime.now(UTC)
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time_module.tzset()

    assert abs((after - before).total_seconds()) < 5
    assert before.utcoffset().total_seconds() == 0
    assert after.utcoffset().total_seconds() == 0


def test_item_age_is_correct_across_an_ambiguous_dst_local_time():
    """A real DST boundary, using fixed instants rather than the wall
    clock. America/New_York left DST at 2019-11-03 06:00 UTC, so local
    01:30 happens twice -- once at 05:30 UTC and again at 06:30 UTC.

    A system that reasoned in local time would compute the same age for
    both, losing an hour. Because every timestamp this project compares
    is UTC, the two must differ by exactly one hour.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    first_pass = datetime(2019, 11, 3, 1, 30, fold=0, tzinfo=eastern).astimezone(UTC)
    second_pass = datetime(2019, 11, 3, 1, 30, fold=1, tzinfo=eastern).astimezone(UTC)

    assert (second_pass - first_pass).total_seconds() == 3600

    first_seen = pd.Series({"n1": pd.Timestamp("2019-11-01 00:00:00")})
    candidates = pd.DataFrame({"news_id": ["n1"]})

    age_first = compute_age_days(
        candidates, pd.Timestamp(first_pass.replace(tzinfo=None)), first_seen
    )
    age_second = compute_age_days(
        candidates, pd.Timestamp(second_pass.replace(tzinfo=None)), first_seen
    )

    elapsed_days = float(age_second.iloc[0]) - float(age_first.iloc[0])
    assert abs(elapsed_days - 1 / 24) < 1e-9, "the repeated local hour must still be an hour apart"


def test_nonexistent_dst_local_time_still_converts_to_a_real_utc_instant():
    """The spring-forward gap: America/New_York jumped 02:00 -> 03:00
    local on 2019-03-10, so local 02:30 never happened. Converting it
    must still yield a well-defined UTC instant rather than raising or
    silently producing a duplicate, so a dataset timestamp landing in
    the gap cannot crash the freshness path.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    gap_local = datetime(2019, 3, 10, 2, 30, tzinfo=eastern)

    as_utc = gap_local.astimezone(UTC)

    assert as_utc.tzinfo is not None
    assert as_utc.utcoffset().total_seconds() == 0
    # PEP 495 resolves the gap deterministically; the exact side matters
    # less than it being defined and usable in real arithmetic.
    assert datetime(2019, 3, 10, 6, 0, tzinfo=UTC) <= as_utc <= datetime(2019, 3, 10, 8, 0, tzinfo=UTC)

    first_seen = pd.Series({"n1": pd.Timestamp("2019-03-09 00:00:00")})
    age = compute_age_days(
        pd.DataFrame({"news_id": ["n1"]}),
        pd.Timestamp(as_utc.replace(tzinfo=None)),
        first_seen,
    )
    assert float(age.iloc[0]) > 0


def test_recommend_generated_at_is_timezone_aware_utc():
    """A real UTC offset on the response, not a naive timestamp a caller
    would have to guess a zone for.
    """
    context = _build_context()
    response = recommend(RecommendationRequest(user_id="u1", num_candidates=3), context)

    assert response.generated_at.tzinfo is not None
    assert response.generated_at.utcoffset().total_seconds() == 0


def test_featureless_users_all_receive_the_same_global_popularity_slate():
    """Documents the real cold-start behaviour rather than implying
    personalization that does not exist: with no durable and no recent
    features, every user gets the same globally popular items.

    This is deliberate. The alternative -- hashing the user id or
    randomising the order to make slates look different -- would be
    fabricated personalization, which is worse than an honest global
    fallback.
    """
    context = _build_context()

    first = recommend(RecommendationRequest(user_id="nobody-a", num_candidates=4), context)
    second = recommend(RecommendationRequest(user_id="nobody-b", num_candidates=4), context)

    assert first.durable_features_used is False and first.recent_features_used is False
    assert second.durable_features_used is False and second.recent_features_used is False
    assert [i.news_id for i in first.recommendations] == [i.news_id for i in second.recommendations]
    assert [i.score for i in first.recommendations] == [i.score for i in second.recommendations]


def test_a_user_with_real_features_is_not_served_the_cold_start_slate():
    """The counterpart: real features must actually change the slate,
    otherwise the fallback would be silently swallowing personalization.
    """
    redis_client = _FakeRedis()
    save_recent_features(
        redis_client,
        RecentUserFeatures(
            user_id="u1", recent_clicked_items=["n1", "n2"],
            impressions_seen=2, clicks_seen=2, last_event_time=None,
        ),
    )
    context = _build_context(redis_client=redis_client)

    known = recommend(RecommendationRequest(user_id="u1", num_candidates=4), context)
    featureless = recommend(RecommendationRequest(user_id="nobody", num_candidates=4), context)

    assert known.recent_features_used is True
    assert featureless.recent_features_used is False
    assert [i.news_id for i in known.recommendations] != [
        i.news_id for i in featureless.recommendations
    ], "real user features must produce a different slate from the global fallback"
