import pandas as pd
import torch

from recommender.data.mind import explode_impressions
from recommender.retrieval.dataset import TwoTowerDataset
from recommender.retrieval.features import (
    CONTENT_DIM,
    build_catalog_arrays,
    build_history_arrays,
    build_item_content_matrix,
    build_item_vocab,
)
from recommender.retrieval.model import TwoTowerModel

NEWS = pd.DataFrame(
    {
        "news_id": ["N1", "N2", "N3"],
        "category": ["sports", "sports", "news"],
        "subcategory": ["ball", "ball", "politics"],
        "title": ["t1", "t2", "t3"],
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


def test_build_item_vocab_reserves_index_zero_for_padding():
    item_vocab, categories, subcategories = build_item_vocab(NEWS)

    assert 0 not in categories.values()
    assert 0 not in subcategories.values()
    assert item_vocab["N1"] == (categories["sports"], subcategories["ball"])


def test_build_history_arrays_masks_padding_and_truncates_to_max_history():
    behaviors = _behaviors(
        [
            (1, "U1", "2019-11-09 10:00:00", "N1 N2", "N3-0"),
            (2, "U2", "2019-11-09 11:00:00", None, "N3-0"),
        ]
    )
    item_vocab, _, _ = build_item_vocab(NEWS)

    cat, _subcat, mask, _rows, impression_row = build_history_arrays(behaviors, item_vocab, max_history=5)

    assert mask[0].tolist() == [1.0, 1.0, 0.0, 0.0, 0.0]  # U1: 2 real items, padded to 5
    assert cat[0, 0] == item_vocab["N1"][0]
    assert mask[1].sum() == 0.0  # U2: no history at all
    assert impression_row[1] == 0
    assert impression_row[2] == 1


def test_user_vector_ignores_masked_padding_positions():
    model = TwoTowerModel(num_categories=3, num_subcategories=3, embedding_dim=4)
    history_cat = torch.tensor([[1, 2, 0, 0]])
    history_subcat = torch.tensor([[1, 2, 0, 0]])
    real_mask = torch.tensor([[1.0, 1.0, 0.0, 0.0]])
    mask_including_padding = torch.tensor([[1.0, 1.0, 1.0, 1.0]])

    content = torch.zeros((1, 4, CONTENT_DIM))
    correctly_masked = model.user_vector(history_cat, history_subcat, real_mask, content)
    incorrectly_unmasked = model.user_vector(
        history_cat, history_subcat, mask_including_padding, content
    )

    # If padding leaked into the average, including it would change the result,
    # since index 0's embedding is a real (if meaningless) trainable vector.
    assert not torch.allclose(correctly_masked, incorrectly_unmasked)


def test_two_tower_forward_produces_one_score_per_example():
    model = TwoTowerModel(num_categories=3, num_subcategories=3, embedding_dim=4)
    batch = 2
    history_cat = torch.zeros(batch, 5, dtype=torch.long)
    history_subcat = torch.zeros(batch, 5, dtype=torch.long)
    mask = torch.zeros(batch, 5)
    cand_cat = torch.tensor([1, 2])
    cand_subcat = torch.tensor([1, 2])

    hist_content = torch.zeros((batch, 5, CONTENT_DIM))
    cand_content = torch.zeros((batch, CONTENT_DIM))
    scores = model(
        history_cat, history_subcat, mask, hist_content, cand_cat, cand_subcat, cand_content
    )

    assert scores.shape == (batch,)


def test_two_tower_dataset_builds_correct_example():
    behaviors = _behaviors([(1, "U1", "2019-11-10 09:00:00", "N1", "N2-1 N3-0")])
    item_vocab, _, _ = build_item_vocab(NEWS)
    _catalog_cat, _catalog_subcat, row_by_news_id = build_catalog_arrays(NEWS, item_vocab)
    content_matrix = build_item_content_matrix(NEWS)
    cat, subcat, mask, rows, impression_row = build_history_arrays(
        behaviors, item_vocab, max_history=5, row_by_news_id=row_by_news_id
    )
    exploded = explode_impressions(behaviors)

    dataset = TwoTowerDataset(
        exploded, impression_row, cat, subcat, mask, rows,
        item_vocab, content_matrix, row_by_news_id,
    )

    assert len(dataset) == 2  # N2 and N3
    _h_cat, _h_subcat, h_mask, _h_content, _c_cat, _c_subcat, _c_content, label = dataset[0]
    assert h_mask.sum().item() == 1.0  # N1 is the only real history item
    assert label.item() in (0.0, 1.0)
