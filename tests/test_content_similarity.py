import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.ranking.baselines import (
    build_content_vectors,
    compute_popularity,
    rank_by_content_similarity,
)

NEWS = pd.DataFrame(
    {
        "news_id": ["N1", "N2", "N3"],
        "category": ["food", "sports", "food"],
        "subcategory": ["fruit", "ball", "drink"],
        "title": ["apple orange fruit basket", "basketball soccer sports team", "apple juice drink"],
        "abstract": ["", "", ""],
        "url": ["u", "u", "u"],
        "title_entities": ["[]", "[]", "[]"],
        "abstract_entities": ["[]", "[]", "[]"],
    }
)


def _behaviors(rows):
    return pd.DataFrame(
        {
            "impression_id": [r[0] for r in rows],
            "user_id": [r[1] for r in rows],
            "time": pd.to_datetime([r[2] for r in rows]),
            "history": [r[3] for r in rows],
            "impressions": [r[4] for r in rows],
        }
    )


def test_ranks_textually_related_candidate_above_unrelated_one():
    # History is a fruit article; candidates are a sports article (unrelated)
    # and an "apple juice" article (shares the word "apple" with history).
    validation = _behaviors([(100, "U1", "2019-11-10 09:00:00", "N1", "N2-0 N3-0")])
    exploded = explode_impressions(validation)
    vectors, row_by_id = build_content_vectors(NEWS)
    popularity = pd.Series(dtype=float)  # unused here; no fallback expected

    ordered = rank_by_content_similarity(exploded, ["N1"], vectors, row_by_id, popularity)

    assert list(ordered["news_id"]) == ["N3", "N2"]  # N3 (apple juice) beats N2 (sports)


def test_falls_back_to_popularity_when_history_is_empty():
    train = _behaviors(
        [
            (1, "U1", "2019-11-09 10:00:00", None, "N2-1"),
            (2, "U2", "2019-11-09 11:00:00", None, "N2-1"),
            (3, "U3", "2019-11-09 12:00:00", None, "N3-1"),
        ]
    )
    popularity = compute_popularity(train)  # N2=2, N3=1

    validation = _behaviors([(100, "U4", "2019-11-10 09:00:00", None, "N3-0 N2-0")])
    exploded = explode_impressions(validation)
    vectors, row_by_id = build_content_vectors(NEWS)

    ordered = rank_by_content_similarity(exploded, [], vectors, row_by_id, popularity)

    assert list(ordered["news_id"]) == ["N2", "N3"]  # popularity order: N2(2) > N3(1)
