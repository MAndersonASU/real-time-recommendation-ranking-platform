import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import ConcatDataset, DataLoader

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import load_catalog, load_split
from recommender.retrieval.content_artifact import save_item_content
from recommender.retrieval.dataset import SampledNegativeDataset, TwoTowerDataset
from recommender.retrieval.features import (
    build_catalog_arrays,
    build_history_arrays,
    build_item_content_matrix,
    build_item_vocab,
    build_user_clicked_rows,
)
from recommender.retrieval.model import TwoTowerModel
from recommender.retrieval.negatives import sample_negatives_for_positives
from recommender.seed import set_seed

MODEL_PATH = Path("data/processed/mind_small/two_tower_model.pt")
TRAIN_REPORT_PATH = Path("data/processed/mind_small/two_tower_train_report.json")
EMBEDDING_DIM = 32
BATCH_SIZE = 2048
NUM_SAMPLED_NEGATIVES = 4
TRAIN_SEED = 42


def build_train_dataset(num_sampled_negatives: int = NUM_SAMPLED_NEGATIVES):
    train = load_split("train")
    news = load_catalog()
    item_vocab, categories, subcategories = build_item_vocab(news)
    catalog_cat, catalog_subcat, row_by_news_id = build_catalog_arrays(news, item_vocab)
    # Fitted here and only here. Every other stage loads this exact
    # matrix, so serving never scores against a differently-oriented
    # SVD basis than the one the model was trained on.
    content_matrix = build_item_content_matrix(news)
    save_item_content(news, content_matrix)

    cat, subcat, mask, history_item_rows, impression_row = build_history_arrays(
        train, item_vocab, row_by_news_id=row_by_news_id
    )
    exploded = explode_impressions(train)
    in_impression_dataset = TwoTowerDataset(
        exploded, impression_row, cat, subcat, mask, history_item_rows,
        item_vocab, content_matrix, row_by_news_id,
    )

    user_clicked_rows = build_user_clicked_rows(train, row_by_news_id)

    positives = exploded[exploded["clicked"] == 1]
    positive_item_rows = np.array([row_by_news_id[nid] for nid in positives["news_id"]])
    positive_impression_rows = positives["impression_id"].map(impression_row).to_numpy()

    sampled_negative_rows = sample_negatives_for_positives(
        positives["user_id"].to_numpy(),
        positive_item_rows,
        user_clicked_rows,
        catalog_size=len(news),
        num_negatives=num_sampled_negatives,
    )
    sampled_negative_dataset = SampledNegativeDataset(
        positive_impression_rows, sampled_negative_rows, cat, subcat, mask, history_item_rows,
        catalog_cat, catalog_subcat, content_matrix,
    )

    dataset = ConcatDataset([in_impression_dataset, sampled_negative_dataset])
    return dataset, len(categories) + 1, len(subcategories) + 1


def train_model(
    max_steps: int,
    batch_size: int = BATCH_SIZE,
    embedding_dim: int = EMBEDDING_DIM,
    dataset=None,
    num_categories=None,
    num_subcategories=None,
    seed: int = TRAIN_SEED,
):
    """Seeds immediately before both the DataLoader and the model are
    constructed, since the DataLoader's `shuffle=True` and the model's
    own weight initialization both draw from torch's global RNG. Two
    runs given the same dataset and seed then produce bit-for-bit
    identical shuffling order and initial weights
    (`tests/test_retrieval_train.py`).
    """
    if dataset is None:
        dataset, num_categories, num_subcategories = build_train_dataset()

    set_seed(seed)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    model = TwoTowerModel(num_categories, num_subcategories, embedding_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    losses = []
    checkpoints = []
    step = 0
    while step < max_steps:
        for h_cat, h_subcat, h_mask, h_content, c_cat, c_subcat, c_content, label in loader:
            optimizer.zero_grad()
            logits = model(h_cat, h_subcat, h_mask, h_content, c_cat, c_subcat, c_content)
            loss = loss_fn(logits, label)
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
            step += 1
            if step % 500 == 0:
                checkpoints.append({"step": step, "mean_loss_last_500": sum(losses[-500:]) / 500})
            if step >= max_steps:
                break

    return model, losses, checkpoints


def main(max_steps: int = 6000) -> None:
    dataset, num_categories, num_subcategories = build_train_dataset()
    print(f"dataset size: {len(dataset)} examples")

    start = time.time()
    model, losses, checkpoints = train_model(
        max_steps, dataset=dataset, num_categories=num_categories, num_subcategories=num_subcategories
    )
    elapsed = time.time() - start

    torch.save(model.state_dict(), MODEL_PATH)
    report = {
        "dataset_size": len(dataset),
        "num_sampled_negatives_per_positive": NUM_SAMPLED_NEGATIVES,
        "seed": TRAIN_SEED,
        "steps": len(losses),
        "batch_size": BATCH_SIZE,
        "embedding_dim": EMBEDDING_DIM,
        "elapsed_seconds": elapsed,
        "first_10_loss_mean": sum(losses[:10]) / len(losses[:10]),
        "last_500_loss_mean": sum(losses[-500:]) / len(losses[-500:]),
        "min_loss": min(losses),
        "checkpoints": checkpoints,
        "final_global_bias": model.global_bias.item(),
    }
    TRAIN_REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
