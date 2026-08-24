import numpy as np
import pandas as pd
import torch

from recommender.ranking.features import build_feature_context, build_ranking_rows
from recommender.retrieval.model import TwoTowerModel

NEWS = pd.DataFrame(
    {
        "news_id": ["N1", "N2", "N3", "N4"],
        "category": ["sports", "sports", "news", "news"],
        "subcategory": ["ball", "ball", "politics", "weather"],
        "title": ["ball game today", "another ball game", "election results", "storm warning"],
        "abstract": ["", "", "", ""],
        "url": ["u", "u", "u", "u"],
        "title_entities": ["[]", "[]", "[]", "[]"],
        "abstract_entities": ["[]", "[]", "[]", "[]"],
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


def _context(train):
    torch.manual_seed(0)
    model = TwoTowerModel(num_categories=3, num_subcategories=4, embedding_dim=4)
    return build_feature_context(train, NEWS, model)


def test_hour_of_day_matches_impression_timestamp_not_some_other_time():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    validation = _behaviors([(100, "U2", "2019-11-10 15:00:00", "N1", "N2-1 N3-0")])

    rows = build_ranking_rows(validation, context)

    assert (rows["hour_of_day"] == 15).all()


def test_user_history_length_counts_real_items_only():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    validation = _behaviors(
        [
            (100, "U2", "2019-11-10 09:00:00", "N1 N2", "N3-0"),
            (101, "U3", "2019-11-10 09:00:00", None, "N3-0"),
        ]
    )

    rows = build_ranking_rows(validation, context)

    assert rows.loc[rows["impression_id"] == 100, "user_history_length"].iloc[0] == 2
    assert rows.loc[rows["impression_id"] == 101, "user_history_length"].iloc[0] == 0


def test_category_match_is_one_only_for_the_users_dominant_history_category():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    # History is all "sports" (N1, N2) -> N1/N2 candidates should match, N3/N4 ("news") should not.
    validation = _behaviors([(100, "U2", "2019-11-10 09:00:00", "N1 N2", "N1-0 N3-0")])

    rows = build_ranking_rows(validation, context).set_index("news_id")

    assert rows.loc["N1", "category_match"] == 1.0
    assert rows.loc["N3", "category_match"] == 0.0


def test_category_match_is_zero_with_no_usable_history_not_a_crash():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    validation = _behaviors([(100, "U2", "2019-11-10 09:00:00", None, "N1-0 N3-0")])

    rows = build_ranking_rows(validation, context)

    assert (rows["category_match"] == 0.0).all()


def test_content_similarity_ranks_same_category_article_above_unrelated_one():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    # History is N1 (ball game) -> N2 (another ball game) should score higher
    # than N4 (storm warning), by TF-IDF content similarity alone.
    validation = _behaviors([(100, "U2", "2019-11-10 09:00:00", "N1", "N2-0 N4-0")])

    rows = build_ranking_rows(validation, context).set_index("news_id")

    assert rows.loc["N2", "content_similarity"] > rows.loc["N4", "content_similarity"]


def test_retrieval_score_matches_a_manual_dot_product_recomputation():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    validation = _behaviors([(100, "U2", "2019-11-10 09:00:00", "N1", "N2-0")])

    rows = build_ranking_rows(validation, context)

    model = context["model"]
    item_vocab = context["item_vocab"]
    with torch.no_grad():
        hist_cat = torch.tensor([[item_vocab["N1"][0]] + [0] * 19])
        hist_subcat = torch.tensor([[item_vocab["N1"][1]] + [0] * 19])
        mask = torch.tensor([[1.0] + [0.0] * 19])
        item_content = context["item_content"]
        row_by_news_id = context["row_by_news_id"]
        hist_content = torch.zeros((1, 20, item_content.shape[1]))
        hist_content[0, 0] = torch.from_numpy(item_content[row_by_news_id["N1"]])
        user_emb = model.user_vector(hist_cat, hist_subcat, mask, hist_content)[0]
        cand_cat = torch.tensor([item_vocab["N2"][0]])
        cand_subcat = torch.tensor([item_vocab["N2"][1]])
        cand_content = torch.from_numpy(item_content[[row_by_news_id["N2"]]])
        item_emb = model.item_vector(cand_cat, cand_subcat, cand_content)[0]
        expected = float(user_emb @ item_emb)

    actual = rows.loc[rows["news_id"] == "N2", "retrieval_score"].iloc[0]
    assert np.isclose(actual, expected, atol=1e-5)


def test_no_impression_row_leaks_a_different_impressions_history():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N1", "N2-1")])
    context = _context(train)
    # Two users with opposite-category histories, each shown a candidate
    # that matches only their OWN history's category. If impression_row
    # ever mapped a row to the wrong impression's history, one of these
    # would flip from a match to a non-match.
    validation = _behaviors(
        [
            (100, "U2", "2019-11-10 09:00:00", "N1", "N2-0"),  # history sports, candidate sports
            (101, "U3", "2019-11-10 09:00:00", "N3", "N4-0"),  # history news, candidate news
        ]
    )

    rows = build_ranking_rows(validation, context)

    row_100 = rows[rows["impression_id"] == 100].iloc[0]
    row_101 = rows[rows["impression_id"] == 101].iloc[0]
    assert row_100["category_match"] == 1.0
    assert row_101["category_match"] == 1.0
