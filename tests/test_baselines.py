import pandas as pd

from recommender.data.mind import explode_impressions
from recommender.ranking.baselines import compute_popularity, rank_by_popularity


def _behaviors(rows):
    return pd.DataFrame(
        {
            "impression_id": [r[0] for r in rows],
            "user_id": [r[1] for r in rows],
            "time": pd.to_datetime([r[2] for r in rows]),
            "history": [None] * len(rows),
            "impressions": [r[3] for r in rows],
        }
    )


def test_compute_popularity_counts_clicks_not_impressions():
    train = _behaviors(
        [
            (1, "U1", "2019-11-09 10:00:00", "A-1 B-0"),
            (2, "U2", "2019-11-09 11:00:00", "A-1 B-0"),
            (3, "U3", "2019-11-09 12:00:00", "A-1 C-0"),
        ]
    )
    popularity = compute_popularity(train)

    assert popularity["A"] == 3  # clicked in all 3 impressions
    assert popularity["B"] == 0  # shown twice, clicked never
    assert popularity["C"] == 0


def test_rank_by_popularity_orders_by_training_clicks_with_deterministic_ties():
    train = _behaviors(
        [
            (1, "U1", "2019-11-09 10:00:00", "A-1"),
            (2, "U2", "2019-11-09 11:00:00", "A-1"),
            (3, "U3", "2019-11-09 12:00:00", "A-1"),
            (4, "U4", "2019-11-09 13:00:00", "B-1"),
        ]
    )
    popularity = compute_popularity(train)  # A=3, B=1

    # Validation impression candidates, deliberately out of popularity order,
    # including D and E which never appeared in training (both popularity 0 -> tie).
    validation = _behaviors([(100, "U5", "2019-11-10 09:00:00", "E-0 D-0 B-1 A-0")])
    exploded = explode_impressions(validation)

    ordered = rank_by_popularity(exploded, popularity)

    assert list(ordered["news_id"]) == ["A", "B", "D", "E"]  # A(3) > B(1) > D=E(0, tie by id)
    assert list(ordered["clicked"]) == [0, 1, 0, 0]
