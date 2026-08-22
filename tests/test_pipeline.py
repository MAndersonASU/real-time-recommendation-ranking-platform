import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from recommender.features.online_features import RecentUserFeatures
from recommender.features.state_store import save_recent_features
from recommender.ranking.baselines import build_content_vectors, compute_popularity
from recommender.ranking.train import MODEL_FEATURE_COLUMNS
from recommender.reranking.freshness import compute_first_seen
from recommender.retrieval.features import build_catalog_arrays, build_item_vocab
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
    catalog_cat, catalog_subcat, _ = build_catalog_arrays(NEWS, item_vocab)

    model = TwoTowerModel(len(categories) + 1, len(subcategories) + 1, embedding_dim=8)
    model.eval()
    catalog_embeddings = compute_catalog_embeddings(model, catalog_cat, catalog_subcat)
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
