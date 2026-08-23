import pandas as pd
import torch

from recommender.retrieval.dataset import SampledNegativeDataset, TwoTowerDataset
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_history_arrays,
    build_item_vocab,
)
from recommender.retrieval.negatives import sample_negatives_for_positives
from recommender.retrieval.train import train_model
from tests.test_pipeline import NEWS

TRAIN_BEHAVIORS = pd.DataFrame(
    {
        "impression_id": [1, 2, 3],
        "user_id": ["u1", "u2", "u3"],
        "time": pd.to_datetime(["2019-11-09T08:00:00", "2019-11-09T09:00:00", "2019-11-09T10:00:00"]),
        "history": ["n1 n2", "n4", "n3 n5"],
        "impressions": ["n3-0 n1-1", "n5-1 n6-0", "n2-0 n7-1"],
    }
)


def _tiny_dataset():
    from recommender.data.mind import explode_impressions

    item_vocab, categories, subcategories = build_item_vocab(NEWS)
    cat, subcat, mask, impression_row = build_history_arrays(TRAIN_BEHAVIORS, item_vocab)
    exploded = explode_impressions(TRAIN_BEHAVIORS)
    in_impression_dataset = TwoTowerDataset(exploded, impression_row, cat, subcat, mask, item_vocab)

    catalog_cat, catalog_subcat, row_by_news_id = build_catalog_arrays(NEWS, item_vocab)
    positives = exploded[exploded["clicked"] == 1]
    positive_item_rows = positives["news_id"].map(row_by_news_id).to_numpy()
    positive_impression_rows = positives["impression_id"].map(impression_row).to_numpy()

    sampled_negative_rows = sample_negatives_for_positives(
        positives["user_id"].to_numpy(),
        positive_item_rows,
        {},
        catalog_size=len(NEWS),
        num_negatives=2,
    )
    sampled_negative_dataset = SampledNegativeDataset(
        positive_impression_rows, sampled_negative_rows, cat, subcat, mask, catalog_cat, catalog_subcat
    )
    from torch.utils.data import ConcatDataset

    dataset = ConcatDataset([in_impression_dataset, sampled_negative_dataset])
    return dataset, len(categories) + 1, len(subcategories) + 1


def test_train_model_is_bit_for_bit_reproducible_given_the_same_seed():
    """Regression test for a real bug, found by audit: training was not
    reproducible -- set_seed was never called from the real training
    entrypoint, and the DataLoader's shuffle order plus the model's own
    weight initialization both draw from torch's unseeded global RNG.
    Fails on the pre-fix code (two runs diverge) and passes once
    train_model seeds before constructing either.
    """
    dataset, num_categories, num_subcategories = _tiny_dataset()

    model_a, losses_a, _ = train_model(
        max_steps=5, dataset=dataset, num_categories=num_categories,
        num_subcategories=num_subcategories, seed=123,
    )
    model_b, losses_b, _ = train_model(
        max_steps=5, dataset=dataset, num_categories=num_categories,
        num_subcategories=num_subcategories, seed=123,
    )

    assert losses_a == losses_b
    for param_a, param_b in zip(model_a.parameters(), model_b.parameters(), strict=True):
        assert torch.equal(param_a, param_b)


def test_train_model_diverges_with_a_different_seed():
    """A sanity check on the test above: two different seeds must not
    coincidentally produce identical results, or the reproducibility
    test above would be meaningless.
    """
    dataset, num_categories, num_subcategories = _tiny_dataset()

    _model_a, losses_a, _ = train_model(
        max_steps=5, dataset=dataset, num_categories=num_categories,
        num_subcategories=num_subcategories, seed=123,
    )
    _model_b, losses_b, _ = train_model(
        max_steps=5, dataset=dataset, num_categories=num_categories,
        num_subcategories=num_subcategories, seed=456,
    )

    assert losses_a != losses_b
