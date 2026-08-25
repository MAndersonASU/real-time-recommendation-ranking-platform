import time
from dataclasses import dataclass
from datetime import UTC, datetime

import faiss
import numpy as np
import pandas as pd
import redis
import skops.io as sio
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
from recommender.retrieval.content_artifact import load_item_content
from recommender.retrieval.features import (
    CONTENT_DIM,
    MAX_HISTORY,
    build_catalog_arrays,
    build_item_vocab,
)
from recommender.retrieval.index import compute_catalog_embeddings
from recommender.retrieval.model import TwoTowerModel
from recommender.retrieval.train import EMBEDDING_DIM
from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH
from recommender.serving.cache import DurableFeatureCache, build_durable_feature_cache
from recommender.serving.contract import (
    MatchedSignals,
    RecommendationRequest,
    RecommendationResponse,
    RecommendedItem,
)
from recommender.serving.errors import DependencyUnavailableError

RETRIEVAL_MULTIPLIER = 5
# Raised from 50 after measuring the real recall/latency tradeoff on the
# tuning fold, never on `validation` (`verify_retrieval_depth` in
# recommender.evaluation.verify_tuning_decisions). Retrieving 50 of
# 51,282 items put the clicked article in front of the ranker on 5.8% of
# tune-fold impressions; 1,000 raises that to 20.9%, and ranking cannot
# recover a click retrieval never surfaced. The cost is real but small:
# end-to-end p50 rises about 4 ms (index search itself stays under a
# millisecond -- the added time is ranking and reranking scoring more
# candidates). Chosen as a judgment call from that measured tradeoff,
# not selected by an automatic rule; see docs/evaluation-integrity.md.
MIN_RETRIEVAL_CANDIDATES = 1000


@dataclass
class ServingContext:
    """Every artifact the live path needs, loaded exactly once -- a real
    request only ever does a lookup or a forward pass through an already-
    trained model, never a training-time computation. Built once at
    service start, not per request.
    """

    item_vocab: dict
    item_content: np.ndarray
    item_row_by_news_id: dict
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
    catalog_cat, catalog_subcat, item_row_by_news_id = build_catalog_arrays(news, item_vocab)
    item_content = load_item_content(news)

    two_tower_model = _load_two_tower_model(len(categories) + 1, len(subcategories) + 1)
    catalog_embeddings = compute_catalog_embeddings(
        two_tower_model, catalog_cat, catalog_subcat, item_content
    )
    faiss_index = faiss.IndexFlatIP(catalog_embeddings.shape[1])
    faiss_index.add(catalog_embeddings)

    tfidf_vectors, tfidf_row_by_id = build_content_vectors(news)
    # sio.load (skops), not joblib.load: joblib is a thin wrapper over
    # pickle, so loading a ranking artifact that way means executing
    # arbitrary code embedded in the file. No `trusted=` list is passed:
    # this project's own real trained model is a plain Pipeline of
    # StandardScaler + LogisticRegression, already confirmed to load
    # with zero untrusted types, so the safe default (raise on anything
    # not already known-safe) is exactly the behavior wanted here -- a
    # future artifact containing an unrecognized type should fail
    # loudly at startup, the same "fails loudly" discipline this
    # function already applies to a missing model file.
    ranking_model = sio.load(RANKING_MODEL_PATH)

    # Exploded once and shared, rather than each function re-deriving its
    # own copy of the same multi-million-row frame -- found to cost
    # ~210MB of real, wasted memory the first time this was profiled
    # (docs/profile-hotspots.md).
    exploded_train = explode_impressions(train)

    return ServingContext(
        item_vocab=item_vocab,
        item_content=item_content,
        item_row_by_news_id=item_row_by_news_id,
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


def encode_recent_history(
    item_ids: list,
    item_vocab: dict,
    max_history: int = MAX_HISTORY,
    item_content: np.ndarray | None = None,
    item_row_by_news_id: dict | None = None,
) -> tuple:
    """The same fixed-length, masked category/subcategory/content
    encoding `build_history_arrays` produces for one offline
    impression's history string, built here instead from a live user's
    recent-clicked-items list (Phase 7) for a single query.

    The content block is gathered from the same catalog content matrix
    the item tower was trained against, so a live query is encoded
    exactly the way a training example was.
    """
    cat = np.zeros((1, max_history), dtype=np.int64)
    subcat = np.zeros((1, max_history), dtype=np.int64)
    mask = np.zeros((1, max_history), dtype=np.float32)
    content_dim = item_content.shape[1] if item_content is not None else CONTENT_DIM
    content = np.zeros((1, max_history, content_dim), dtype=np.float32)

    for j, news_id in enumerate(item_ids[-max_history:]):
        if news_id in item_vocab:
            cat[0, j], subcat[0, j] = item_vocab[news_id]
            mask[0, j] = 1.0
            if item_content is not None and item_row_by_news_id is not None:
                row = item_row_by_news_id.get(news_id)
                if row is not None:
                    content[0, j] = item_content[row]
    return cat, subcat, mask, content


def recommend(
    request: RecommendationRequest,
    context: ServingContext,
    stage_timings: dict[str, float] | None = None,
    use_recent_features: bool = True,
    include_matched_signals: bool = False,
    capture_candidates: list | None = None,
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

    `capture_candidates`, when given a list, is extended with the real
    news_ids this call retrieved *before* ranking and reranking narrowed
    them -- the same opt-in instrumentation idea as `stage_timings`, and
    for the same reason: it reads the real code path rather than a
    reimplementation kept in sync by hand. It lets an evaluation separate
    a retrieval miss (the clicked item was never a candidate) from a
    ranking miss (it was retrieved, then ranked out of the slate), which
    a single end-to-end hit rate cannot distinguish.

    `include_matched_signals`, when True, captures each recommended
    item's real ranking-model input features into the response
    (`MatchedSignals`, recommender.serving.contract) at the exact point
    they already exist in `slate` -- opt-in, since only the explanation
    layer (recommender.explanation) needs this, not an ordinary request.
    """
    def _stage_start() -> float:
        return time.perf_counter() if stage_timings is not None else 0.0

    def _stage_end(name: str, start: float) -> None:
        if stage_timings is not None:
            stage_timings[name] = (time.perf_counter() - start) * 1000

    t = _stage_start()
    try:
        lookup = get_online_features(
            request.user_id,
            context.durable_cache.features_by_user,
            context.redis_client,
            use_recent_features=use_recent_features,
        )
    except redis.exceptions.RedisError as exc:
        raise DependencyUnavailableError("redis_unavailable") from exc
    history_ids = lookup.recent.recent_clicked_items
    _stage_end("feature_lookup_ms", t)

    t = _stage_start()
    hist_cat, hist_subcat, hist_mask, hist_content = encode_recent_history(
        history_ids, context.item_vocab,
        item_content=context.item_content,
        item_row_by_news_id=context.item_row_by_news_id,
    )
    try:
        with torch.no_grad():
            user_emb = context.two_tower_model.user_vector(
                torch.from_numpy(hist_cat),
                torch.from_numpy(hist_subcat),
                torch.from_numpy(hist_mask),
                torch.from_numpy(hist_content),
            ).numpy()
    except RuntimeError as exc:
        # Narrow to this one call: a RuntimeError from *this specific*
        # torch forward pass plausibly means the model itself is in a
        # bad state (e.g. a resource exhaustion error). A RuntimeError
        # from anywhere else in this function is a real bug and must not
        # be caught here.
        raise DependencyUnavailableError("two_tower_inference_failed") from exc
    _stage_end("embedding_ms", t)

    t = _stage_start()
    n_retrieve = min(
        max(request.num_candidates * RETRIEVAL_MULTIPLIER, MIN_RETRIEVAL_CANDIDATES),
        context.faiss_index.ntotal,
    )
    # A user with no usable click history produces a genuinely zero-norm
    # user vector: `user_vector` averages the item vectors of whatever is
    # in the history, and an empty (fully masked) history sums to zero.
    # Querying an inner-product index with a zero vector scores *every*
    # catalog item exactly 0.0, so Faiss returns an arbitrary tie order --
    # the same arbitrary slate for every history-less user, with the
    # ranking model then seeing a constant retrieval_score and assigning
    # every candidate an identical probability. Popularity is a real
    # signal in exactly this situation, so cold-start retrieval uses it
    # instead of a search that has no signal to rank by.
    has_retrieval_signal = bool(np.linalg.norm(user_emb))
    if has_retrieval_signal:
        try:
            retrieval_scores, item_rows = context.faiss_index.search(user_emb, n_retrieve)
        except RuntimeError as exc:
            # Narrow to this one call, for the same reason as above -- a
            # RuntimeError specifically from Faiss's own search call, not a
            # stand-in for any RuntimeError anywhere in this function.
            raise DependencyUnavailableError("faiss_search_failed") from exc
        candidate_news_ids = context.news_ids[item_rows[0]]
        candidate_retrieval_scores = retrieval_scores[0]
    else:
        # Reindexed over the *whole* catalog, not just the items that
        # happen to appear in `popularity`: an item with no training
        # clicks has a real popularity of zero, not a missing value, and
        # dropping those would leave fewer than n_retrieve candidates
        # whenever the training split covers only part of the catalog.
        catalog_popularity = (
            context.popularity.reindex(context.news_ids).fillna(0.0).sort_values(ascending=False)
        )
        top_popular = catalog_popularity.head(n_retrieve)
        candidate_news_ids = top_popular.index.to_numpy()
        # Scaled to [0, 1] so retrieval_score keeps a comparable meaning
        # to an inner-product score rather than an unbounded click count.
        max_clicks = float(top_popular.max()) or 1.0
        candidate_retrieval_scores = (top_popular.to_numpy() / max_clicks).astype(np.float32)
    if capture_candidates is not None:
        capture_candidates.extend(candidate_news_ids.tolist())
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

    # Falls back to a genuinely UTC clock, not bare local wall-clock
    # time, when a caller (e.g. /demo, which never sets request_time)
    # supplies none -- every other naive timestamp in this project
    # represents naive-but-UTC-by-convention (MIND's own timestamps,
    # `first_seen`, and so on), and on a server whose OS timezone isn't
    # UTC, a bare `datetime.now()` would be naive-but-*local*, silently
    # inconsistent with that convention. `datetime.now(UTC)` is
    # genuinely UTC; `.replace(tzinfo=None)` keeps it naive-typed so it
    # stays directly comparable to those other naive-UTC values rather
    # than needing every downstream consumer to become timezone-aware.
    has_real_request_time = request.request_time is not None
    request_time = request.request_time or datetime.now(UTC).replace(tzinfo=None)
    frame = pd.DataFrame(
        {
            "news_id": candidate_news_ids,
            "retrieval_score": candidate_retrieval_scores,
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
    # Freshness only applies when the caller supplied a real,
    # dataset-relevant request_time (replay/evaluation always does).
    # MIND is a frozen November 2019 dataset with no ongoing ingestion,
    # so "freshness relative to right now" has no real meaning for an
    # interactive request that never specified what "now" should be
    # relative to the dataset -- every known item would compare as
    # several thousand days old against the real wall clock, and
    # (correctly, since unknown-first-seen items are no longer treated
    # as age zero -- see compute_age_days) nothing would ever satisfy
    # the quota anyway. Applying it regardless would either silently do
    # nothing useful or -- with the old age-zero-for-unseen-items
    # fallback -- systematically favor items this project has no real
    # history for, which is not "freshness," just noise.
    if has_real_request_time:
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

    matched_signals = None
    if include_matched_signals:
        matched_signals = {
            row.news_id: MatchedSignals(
                category_match=bool(row.category_match),
                content_similarity=float(row.content_similarity),
                retrieval_score=float(row.retrieval_score),
                user_history_length=int(lookup.durable.lifetime_click_count),
            )
            for row in slate.itertuples()
        }

    return RecommendationResponse(
        user_id=request.user_id,
        recommendations=recommendations,
        durable_features_used=not lookup.durable_is_fallback,
        recent_features_used=not lookup.recent_is_fallback,
        # Genuinely tz-aware UTC, not naive: this field is pure output
        # (echoed to the client, never compared against an internal
        # naive-UTC-by-convention timestamp), so there's no mixing risk
        # here, and a real, explicit UTC offset in the serialized
        # response is strictly more useful to a caller than a naive
        # value they'd have to assume a timezone for.
        generated_at=datetime.now(UTC),
        matched_signals=matched_signals,
    )
