import json
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from recommender.data.mind import explode_impressions
from recommender.evaluation.contract import load_catalog, load_split
from recommender.retrieval.dataset import TwoTowerDataset
from recommender.retrieval.features import build_history_arrays, build_item_vocab
from recommender.retrieval.model import TwoTowerModel

MODEL_PATH = Path("data/processed/mind_small/two_tower_model.pt")
TRAIN_REPORT_PATH = Path("data/processed/mind_small/two_tower_train_report.json")
EMBEDDING_DIM = 32
BATCH_SIZE = 2048


def build_train_dataset():
    train = load_split("train")
    news = load_catalog()
    item_vocab, categories, subcategories = build_item_vocab(news)
    cat, subcat, mask, impression_row = build_history_arrays(train, item_vocab)
    exploded = explode_impressions(train)
    dataset = TwoTowerDataset(exploded, impression_row, cat, subcat, mask, item_vocab)
    return dataset, len(categories) + 1, len(subcategories) + 1


def train_model(
    max_steps: int,
    batch_size: int = BATCH_SIZE,
    embedding_dim: int = EMBEDDING_DIM,
    dataset=None,
    num_categories=None,
    num_subcategories=None,
):
    if dataset is None:
        dataset, num_categories, num_subcategories = build_train_dataset()

    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    model = TwoTowerModel(num_categories, num_subcategories, embedding_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    losses = []
    checkpoints = []
    step = 0
    while step < max_steps:
        for h_cat, h_subcat, h_mask, c_cat, c_subcat, label in loader:
            optimizer.zero_grad()
            logits = model(h_cat, h_subcat, h_mask, c_cat, c_subcat)
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
