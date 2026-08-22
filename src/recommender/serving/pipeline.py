import time
from dataclasses import dataclass
from datetime import datetime

import faiss
import joblib
import numpy as np
import pandas as pd
import torch

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import load_catalog, load_split
from recommender.features.cold_start import get_online_features
from recommender.features.state_store import build_client
from recommender.ranking.baselines import build_content_vectors, compute_popularity
from recommender.ranking.features import content_profile
from recommender.ranking.train import MODEL_FEATURE_COLUMNS
from recommender.ranking.train import MODEL_PATH as RANKING_MODEL_PATH
from recommender.reranking.diversity import build_diverse_slate
from recommender.reranking.freshness import (
    apply_freshness_quota,
    compute_age_days,
    compute_first_seen,
)
from recommender.retrieval.features import MAX_HISTORY, build_catalog_arrays, build_item_vocab
from recommender.retrieval.index import compute_catalog_embeddings
from recommender.retrieval.model import TwoTowerModel
from recommender.retrieval.train import EMBEDDING_DIM
from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH
from recommender.serving.cache import DurableFeatureCache, build_durable_feature_cache
from recommender.serving.contract import (
    RecommendationRequest,
    RecommendationResponse,
    RecommendedItem,
)

RETRIEVAL_MULTIPLIER = 5
MIN_RETRIEVAL_CANDIDATES = 50


@dataclass
class ServingContext:
    """Every artifact the live path needs, loaded exactly once -- a real
    request only ever does a lookup or a forward pass through an already-
    trained model, never a training-time computation. Built once at
    service start, not per request.
    """

    item_vocab: dict
    news_ids: np.ndarray
    category_by_id: pd.Series
    tfidf_vectors: object
    tfidf_row_by_id: dict
    faiss_index: faiss.IndexFlatIP
    two_tower_model: TwoTowerModel
    ranking_model: object
    durable_cache: DurableFeatureCache
    first_seen: pd.Series
    popularity: pd.Series
    redis_client: object


def _load_two_tower_model(num_categories: int, num_subcategories: int) -> TwoTowerModel:
    model = TwoTowerModel(num_categories, num_subcategories, EMBEDDING_DIM)
    state = torch.load(RETRIEVAL_MODEL_PATH, weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model


def build_serving_context(redis_url: str = "redis://localhost:6379/0") -> ServingContext:
    """Loads the trained two-tower model, builds a fresh exact Faiss index
    from its current catalog embeddings, loads the trained ranking model,
    and computes durable per-user features from the `validation` split --
    the most recent offline split, so its `history` field carries the
    longest available click history for each training-window user.

    Also caps PyTorch's own intraop thread count to 1 for the whole
    process. Profiling found a single request's CPU time at ~5x its own
    wall time -- torch spreading one request's math across several
    threads by default -- and a real concurrency test confirmed the
    fix: at concurrency 4, throughput rose from 62.7 to 80.3 req/s and
    p50 latency dropped from 61ms to 48ms (docs/optimization.md). This
    process expects to serve many concurrent requests, not minimize one
    request's own wall time in isolation, so a single math thread per
    operation -- leaving concurrency to the request-level thread pool
    instead -- is the right tradeoff here.
    """
    torch.set_num_threads(1)

    news = load_catalog()
    train = load_split("train")
    item_vocab, categories, subcategories = build_item_vocab(news)
    catalog_cat, catalog_subcat, _ = build_catalog_arrays(news, item_vocab)

    two_tower_model = _load_two_tower_model(len(categories) + 1, len(subcategories) + 1)
    catalog_embeddings = compute_catalog_embeddings(two_tower_model, catalog_cat, catalog_subcat)
    faiss_index = faiss.IndexFlatIP(catalog_embeddings.shape[1])
    faiss_index.add(catalog_embeddings)

    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)
    ranking_model = joblib.load(RANKING_MODEL_PATH)

    # Exploded once and shared, rather than each function re-deriving its
    # own copy of the same multi-million-row frame -- found to cost
    # ~210MB of real, wasted memory the first time this was profiled
    # (docs/profile-hotspots.md).
    exploded_train = explode_impressions(train)

    return ServingContext(
        item_vocab=item_vocab,
        news_ids=news["news_id"].to_numpy(),
        category_by_id=news.set_index("news_id")["category"],
        tfidf_vectors=tfidf_vectors,
        tfidf_row_by_id=tfidf_row_by_id,
        faiss_index=faiss_index,
        two_tower_model=two_tower_model,
        ranking_model=ranking_model,
        durable_cache=build_durable_feature_cache(load_split("validation"), news),
        first_seen=compute_first_seen(train, exploded=exploded_train),
        popularity=compute_popularity(train, exploded=exploded_train),
        redis_client=build_client(redis_url),
    )


def encode_recent_history(item_ids: list, item_vocab: dict, max_history: int = MAX_HISTORY) -> tuple:
    """The same fixed-length, masked category/subcategory encoding
    `build_history_arrays` produces for one offline impression's history
    string, built here instead from a live user's recent-clicked-items
    list (Phase 7) for a single query.
    """
    cat = np.zeros((1, max_history), dtype=np.int64)
    subcat = np.zeros((1, max_history), dtype=np.int64)
    mask = np.zeros((1, max_history), dtype=np.float32)
    for j, news_id in enumerate(item_ids[-max_history:]):
        if news_id in item_vocab:
            cat[0, j], subcat[0, j] = item_vocab[news_id]
            mask[0, j] = 1.0
    return cat, subcat, mask


def recommend(
    request: RecommendationRequest,
    context: ServingContext,
    stage_timings: dict[str, float] | None = None,
    use_recent_features: bool = True,
) -> RecommendationResponse:
    """Online features -> user embedding -> candidate retrieval -> ranking
    -> reranking -> a Top-K response, exactly the phase's named path.

    One disclosed asymmetry between this live path and offline training:
    the two-tower embedding and the content-similarity profile here only
    ever see a user's last 20 recent clicks, since that is the cap
    Phase 7's low-latency store chose (docs/state-store.md). Offline
    training's own content profile (`ranking/features.py`) pools a user's
    entire history string, uncapped. This is a real, disclosed
    consequence of Phase 7's own latency/storage tradeoff, not a bug --
    `user_history_length` below instead uses the durable
    `lifetime_click_count` specifically because that one field *does*
    carry the same uncapped meaning training used.

    `stage_timings`, when given a dict, gets one entry per stage in
    milliseconds -- opt-in instrumentation of this exact code path, not a
    separate copy kept in sync by hand. Left None by default so a normal
    request pays only the cost of a few `perf_counter()` calls, not any
    bookkeeping overhead.

    `use_recent_features`, when False, forces the online lookup to skip
    Redis entirely (recommender.features.cold_start.get_online_features)
    -- the recent-streaming-features ablation (docs/ablations.md), not a
    normal request path.
    """
    def _stage_start() -> float:
        return time.perf_counter() if stage_timings is not None else 0.0

    def _stage_end(name: str, start: float) -> None:
        if stage_timings is not None:
            stage_timings[name] = (time.perf_counter() - start) * 1000

    t = _stage_start()
    lookup = get_online_features(
        request.user_id,
        context.durable_cache.features_by_user,
        context.redis_client,
        use_recent_features=use_recent_features,
    )
    history_ids = lookup.recent.recent_clicked_items
    _stage_end("feature_lookup_ms", t)

    t = _stage_start()
    hist_cat, hist_subcat, hist_mask = encode_recent_history(history_ids, context.item_vocab)
    with torch.no_grad():
        user_emb = context.two_tower_model.user_vector(
            torch.from_numpy(hist_cat), torch.from_numpy(hist_subcat), torch.from_numpy(hist_mask)
        ).numpy()
    _stage_end("embedding_ms", t)

    t = _stage_start()
    n_retrieve = min(
        max(request.num_candidates * RETRIEVAL_MULTIPLIER, MIN_RETRIEVAL_CANDIDATES),
        context.faiss_index.ntotal,
    )
    retrieval_scores, item_rows = context.faiss_index.search(user_emb, n_retrieve)
    candidate_news_ids = context.news_ids[item_rows[0]]
    _stage_end("retrieval_ms", t)

    t = _stage_start()
    profile = content_profile(history_ids, context.tfidf_vectors, context.tfidf_row_by_id)
    cats = np.array([context.category_by_id.get(nid) for nid in candidate_news_ids])
    user_dominant_category = lookup.durable.dominant_category
    category_matches = (
        (cats == user_dominant_category).astype(float)
        if user_dominant_category is not None
        else np.zeros(len(candidate_news_ids))
    )
    if profile is not None:
        tfidf_rows = np.array([context.tfidf_row_by_id[nid] for nid in candidate_news_ids])
        content_sims = np.asarray(context.tfidf_vectors[tfidf_rows] @ profile).ravel()
    else:
        content_sims = np.zeros(len(candidate_news_ids))

    request_time = request.request_time or datetime.now()  # noqa: DTZ005 -- naive, matches every other timestamp in this project
    frame = pd.DataFrame(
        {
            "news_id": candidate_news_ids,
            "retrieval_score": retrieval_scores[0],
            "category_match": category_matches,
            "content_similarity": content_sims,
            "user_history_length": lookup.durable.lifetime_click_count,
            "hour_of_day": request_time.hour,
        }
    )
    _stage_end("feature_build_ms", t)

    t = _stage_start()
    # .to_numpy(), not the DataFrame itself -- train.py fits this same
    # pipeline on a plain array (no recorded feature names), and passing
    # a named DataFrame here instead triggers a real sklearn mismatch
    # warning despite being otherwise harmless.
    frame["ranking_score"] = context.ranking_model.predict_proba(
        frame[MODEL_FEATURE_COLUMNS].to_numpy()
    )[:, 1]
    _stage_end("ranking_ms", t)

    t = _stage_start()
    frame["age_days"] = compute_age_days(frame, pd.Timestamp(request_time), context.first_seen)
    slate = build_diverse_slate(
        frame, "ranking_score", request.num_candidates, context.category_by_id,
        context.tfidf_vectors, context.tfidf_row_by_id,
    )
    slate = apply_freshness_quota(slate, frame, "ranking_score")
    slate = slate.sort_values("ranking_score", ascending=False).head(request.num_candidates).reset_index(drop=True)
    _stage_end("reranking_ms", t)

    recommendations = [
        RecommendedItem(
            news_id=row.news_id,
            score=float(row.ranking_score),
            rank=i + 1,
            category=context.category_by_id.get(row.news_id),
        )
        for i, row in enumerate(slate.itertuples())
    ]

    return RecommendationResponse(
        user_id=request.user_id,
        recommendations=recommendations,
        durable_features_used=not lookup.durable_is_fallback,
        recent_features_used=not lookup.recent_is_fallback,
        generated_at=datetime.now(),  # noqa: DTZ005 -- naive, matches every other timestamp in this project
    )
