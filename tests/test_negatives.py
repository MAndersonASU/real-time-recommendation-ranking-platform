import numpy as np
import pandas as pd

from recommender.retrieval.dataset import SampledNegativeDataset
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_history_arrays,
    build_item_vocab,
    build_user_clicked_rows,
)
from recommender.retrieval.negatives import sample_negative_rows, sample_negatives_for_positives

NEWS = pd.DataFrame(
    {
        "news_id": ["N0", "N1", "N2", "N3", "N4"],
        "category": ["sports", "sports", "news", "news", "food"],
        "subcategory": ["ball", "ball", "politics", "politics", "drink"],
        "title": ["t0", "t1", "t2", "t3", "t4"],
        "abstract": [""] * 5,
        "url": ["u"] * 5,
        "title_entities": ["[]"] * 5,
        "abstract_entities": ["[]"] * 5,
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


def test_build_catalog_arrays_matches_item_vocab():
    item_vocab, _, _ = build_item_vocab(NEWS)
    cat, subcat, row_by_news_id = build_catalog_arrays(NEWS, item_vocab)

    for news_id, row in row_by_news_id.items():
        assert (cat[row], subcat[row]) == item_vocab[news_id]


def test_build_user_clicked_rows_only_reflects_given_split():
    train = _behaviors(
        [
            (1, "U1", "2019-11-09 10:00:00", None, "N0-1 N1-0"),
            (2, "U1", "2019-11-09 11:00:00", None, "N2-1 N3-0"),
            (3, "U2", "2019-11-09 12:00:00", None, "N4-0 N3-1"),
        ]
    )
    item_vocab, _, _ = build_item_vocab(NEWS)
    _, _, row_by_news_id = build_catalog_arrays(NEWS, item_vocab)

    clicked = build_user_clicked_rows(train, row_by_news_id)

    assert clicked["U1"] == {row_by_news_id["N0"], row_by_news_id["N2"]}
    assert clicked["U2"] == {row_by_news_id["N3"]}


def test_sample_negative_rows_never_returns_excluded_or_positive_item():
    # Catalog has 5 items; exclude 3 of them plus the positive -- only row 4 is safe.
    rng = np.random.default_rng(0)
    user_clicked_rows = {"U1": {0, 1, 2}}

    negatives = sample_negative_rows(
        user_id="U1",
        positive_row=3,
        user_clicked_rows=user_clicked_rows,
        catalog_size=5,
        num_negatives=20,
        rng=rng,
    )

    assert set(negatives) == {4}  # the only row that isn't excluded or the positive
    assert len(negatives) == 20  # still terminates and fills the full request


def test_sample_negatives_for_positives_shape():
    user_ids = np.array(["U1", "U2", "U1"])
    positive_rows = np.array([0, 1, 2])
    user_clicked_rows = {"U1": {0}, "U2": {1}}

    negatives = sample_negatives_for_positives(
        user_ids, positive_rows, user_clicked_rows, catalog_size=5, num_negatives=3
    )

    assert negatives.shape == (3, 3)


def test_sampled_negative_dataset_always_labels_zero():
    train = _behaviors([(1, "U1", "2019-11-09 10:00:00", "N0", "N1-1 N2-0")])
    item_vocab, _, _ = build_item_vocab(NEWS)
    cat, subcat, mask, impression_row = build_history_arrays(train, item_vocab, max_history=5)
    catalog_cat, catalog_subcat, _row_by_news_id = build_catalog_arrays(NEWS, item_vocab)

    impression_rows = np.array([impression_row[1]])
    negative_rows = np.array([[3, 4]])  # pretend these were already sampled

    dataset = SampledNegativeDataset(
        impression_rows, negative_rows, cat, subcat, mask, catalog_cat, catalog_subcat
    )

    assert len(dataset) == 2
    for i in range(len(dataset)):
        *_rest, label = dataset[i]
        assert label.item() == 0.0
