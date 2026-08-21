import pandas as pd

from recommender.ranking.baselines import build_content_vectors
from recommender.reranking.diversity import build_diverse_slate


def _news(rows):
    return pd.DataFrame(
        {
            "news_id": [r[0] for r in rows],
            "category": [r[1] for r in rows],
            "subcategory": ["x"] * len(rows),
            "title": [r[2] for r in rows],
            "abstract": [""] * len(rows),
            "url": ["u"] * len(rows),
            "title_entities": ["[]"] * len(rows),
            "abstract_entities": ["[]"] * len(rows),
        }
    )


def _candidates(scored):
    return pd.DataFrame({"news_id": [s[0] for s in scored], "score": [s[1] for s in scored]})


def test_category_cap_blocks_excess_same_category_items_in_the_constrained_pass():
    news = _news(
        [
            ("S1", "sports", "soccer match highlights team alpha"),
            ("S2", "sports", "basketball tournament finals recap"),
            ("S3", "sports", "tennis open championship results"),
            ("S4", "sports", "hockey playoff overtime thriller"),
            ("S5", "sports", "golf major leaderboard update"),
            ("N1", "news", "city council votes on new budget"),
        ]
    )
    vectors, row_by_id = build_content_vectors(news)
    category_by_id = news.set_index("news_id")["category"]

    candidates = _candidates(
        [("S1", 10), ("S2", 9), ("S3", 8), ("S4", 7), ("S5", 6), ("N1", 5)]
    )

    slate = build_diverse_slate(
        candidates,
        score_column="score",
        k=5,
        category_by_id=category_by_id,
        tfidf_vectors=vectors,
        tfidf_row_by_id=row_by_id,
        max_per_category=2,
        near_duplicate_threshold=0.99,
    )

    # Constrained pass picks S1, S2 (cap reached), then N1; relaxed fill
    # brings in S3, S4 to reach k=5 even though sports is already at cap.
    assert list(slate["news_id"]) == ["S1", "S2", "N1", "S3", "S4"]
    assert len(slate) == 5


def test_near_duplicate_is_skipped_even_when_category_cap_would_allow_it():
    news = _news(
        [
            ("D1", "politics", "election results breaking news today across the nation"),
            ("D2", "politics", "election results breaking news today across the nation"),
            ("T1", "tech", "new smartphone chip benchmark scores released"),
            ("N1", "news", "city council votes on new budget"),
        ]
    )
    vectors, row_by_id = build_content_vectors(news)
    category_by_id = news.set_index("news_id")["category"]

    candidates = _candidates([("D1", 10), ("D2", 9), ("T1", 8), ("N1", 7)])

    slate = build_diverse_slate(
        candidates,
        score_column="score",
        k=3,
        category_by_id=category_by_id,
        tfidf_vectors=vectors,
        tfidf_row_by_id=row_by_id,
        max_per_category=5,  # cap disabled -- isolates the duplicate check
        near_duplicate_threshold=0.5,
    )

    # D2 is an exact text duplicate of D1 (cosine similarity 1.0) -> skipped
    # even though the category cap alone would have allowed it.
    assert "D2" not in list(slate["news_id"])
    assert list(slate["news_id"]) == ["D1", "T1", "N1"]


def test_relaxed_fill_still_returns_k_items_when_constraints_would_underfill():
    news = _news(
        [
            ("C1", "catA", "alpha story one"),
            ("C2", "catA", "beta story two entirely different words"),
            ("C3", "catB", "gamma story three"),
        ]
    )
    vectors, row_by_id = build_content_vectors(news)
    category_by_id = news.set_index("news_id")["category"]

    candidates = _candidates([("C1", 10), ("C2", 9), ("C3", 8)])

    slate = build_diverse_slate(
        candidates,
        score_column="score",
        k=3,
        category_by_id=category_by_id,
        tfidf_vectors=vectors,
        tfidf_row_by_id=row_by_id,
        max_per_category=1,  # constrained pass alone could only pick 2 (C1, C3)
        near_duplicate_threshold=0.99,
    )

    assert len(slate) == 3
    assert set(slate["news_id"]) == {"C1", "C2", "C3"}


def test_slate_never_exceeds_the_number_of_available_candidates():
    news = _news([("A1", "cat", "one story"), ("A2", "cat", "two different story")])
    vectors, row_by_id = build_content_vectors(news)
    category_by_id = news.set_index("news_id")["category"]

    candidates = _candidates([("A1", 10), ("A2", 9)])

    slate = build_diverse_slate(
        candidates,
        score_column="score",
        k=5,
        category_by_id=category_by_id,
        tfidf_vectors=vectors,
        tfidf_row_by_id=row_by_id,
    )

    assert len(slate) == 2
