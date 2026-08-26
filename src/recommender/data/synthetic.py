"""Generates a small, entirely synthetic stand-in for every artifact the
serving container loads at startup.

The real catalog, splits, and trained models all derive from the MIND
dataset, which is licensed and has never been redistributed by this
project (`docs/dataset-source.md`). That is why the containerized API
could not be exercised in CI: the image starts, fails to load its
artifacts, and exits. Everything written here is generated from a seeded
random number generator and a fixed word list, so it carries no licensed
content at all, and it is written to the same paths the real artifacts
occupy so the serving code needs no CI-only branch.

These artifacts are for wiring verification only -- proving the
container starts, loads its models, answers `/health` and `/ready`, and
returns a contract-valid `/recommend` response. The numbers such a model
produces are meaningless, and no evaluation result in this project is
ever computed from them.
"""

import numpy as np
import pandas as pd
import skops.io as sio
import torch

from recommender.evaluation.contract import CATALOG_PATH, SPLITS_DIR
from recommender.ranking.train import MODEL_PATH as RANKING_MODEL_PATH
from recommender.ranking.train import train_ranking_model
from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH
from recommender.seed import set_seed

SEED = 7
NUM_ITEMS = 400
NUM_USERS = 60
NUM_IMPRESSIONS_PER_SPLIT = 120
CANDIDATES_PER_IMPRESSION = 8

CATEGORIES = ["sports", "tech", "news", "finance", "health", "travel"]
SUBCATEGORIES = ["alpha", "beta", "gamma", "delta"]
WORDS = [
    "market", "team", "device", "policy", "study", "launch", "record", "budget",
    "season", "research", "update", "report", "growth", "player", "system",
]


def _synthetic_news(rng: np.random.Generator) -> pd.DataFrame:
    news_ids = [f"N{i}" for i in range(NUM_ITEMS)]
    return pd.DataFrame(
        {
            "news_id": news_ids,
            "category": rng.choice(CATEGORIES, NUM_ITEMS),
            "subcategory": rng.choice(SUBCATEGORIES, NUM_ITEMS),
            # Distinct wording per item, so the content features that
            # separate two articles in one subcategory have something
            # real to separate.
            "title": [" ".join(rng.choice(WORDS, 5)) for _ in range(NUM_ITEMS)],
            "abstract": [" ".join(rng.choice(WORDS, 12)) for _ in range(NUM_ITEMS)],
            "url": [""] * NUM_ITEMS,
            "title_entities": ["[]"] * NUM_ITEMS,
            "abstract_entities": ["[]"] * NUM_ITEMS,
        }
    )


def _synthetic_behaviors(rng: np.random.Generator, news_ids: list, start_id: int, day: str) -> pd.DataFrame:
    rows = []
    for i in range(NUM_IMPRESSIONS_PER_SPLIT):
        user_id = f"U{rng.integers(0, NUM_USERS)}"
        history = " ".join(rng.choice(news_ids, rng.integers(1, 12), replace=False))
        candidates = rng.choice(news_ids, CANDIDATES_PER_IMPRESSION, replace=False)
        # At least one real click per impression, so evaluation code that
        # skips click-free impressions still has rows to work with.
        labels = [0] * CANDIDATES_PER_IMPRESSION
        labels[int(rng.integers(0, CANDIDATES_PER_IMPRESSION))] = 1
        impressions = " ".join(f"{nid}-{label}" for nid, label in zip(candidates, labels, strict=True))
        rows.append(
            {
                "impression_id": start_id + i,
                "user_id": user_id,
                "time": pd.Timestamp(f"{day} 08:00:00") + pd.Timedelta(minutes=i),
                "history": history,
                "impressions": impressions,
            }
        )
    return pd.DataFrame(rows)


def generate() -> dict:
    """Writes the synthetic catalog, splits, and trained models, and
    returns a short summary of what was produced.
    """
    set_seed(SEED)
    rng = np.random.default_rng(SEED)

    news = _synthetic_news(rng)
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    news.to_parquet(CATALOG_PATH)

    news_ids = news["news_id"].tolist()
    for offset, (split, day) in enumerate(
        [("train", "2019-11-09"), ("validation", "2019-11-14"), ("replay", "2019-11-15")]
    ):
        behaviors = _synthetic_behaviors(rng, news_ids, offset * 10000, day)
        split_dir = SPLITS_DIR / split
        split_dir.mkdir(parents=True, exist_ok=True)
        behaviors.to_parquet(split_dir / "behaviors.parquet")

    # Deliberately trained through the real code paths, not hand-built:
    # an artifact produced some other way could load fine while the real
    # training path was broken, which is precisely what this is meant to
    # catch.
    from recommender.retrieval.train import build_train_dataset, train_model

    dataset, num_categories, num_subcategories = build_train_dataset(num_sampled_negatives=1)
    model, _losses, _checkpoints = train_model(
        max_steps=30, batch_size=64, dataset=dataset,
        num_categories=num_categories, num_subcategories=num_subcategories,
    )
    RETRIEVAL_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), RETRIEVAL_MODEL_PATH)

    # Publish the bundle manifest, exactly as the real training path
    # does. These artifacts were produced together by one run and are a
    # coherent set, so they are entitled to a manifest saying so.
    #
    # Not optional: serving refuses artifacts that arrive without a
    # manifest, because that is the state a partially failed training run
    # leaves behind. Generating a synthetic set without one made the
    # container fail its own health check -- the fail-closed rule working
    # correctly against a generator that had not caught up with it.
    from datetime import UTC, datetime

    from recommender.retrieval.bundle import build_manifest, write_manifest
    from recommender.retrieval.content_artifact import CONTENT_ARTIFACT_PATH
    from recommender.retrieval.features import CONTENT_DIM
    from recommender.retrieval.train import EMBEDDING_DIM

    write_manifest(
        build_manifest(
            retrieval_model_path=RETRIEVAL_MODEL_PATH,
            content_artifact_path=CONTENT_ARTIFACT_PATH,
            catalog_path=CATALOG_PATH,
            content_dim=CONTENT_DIM,
            embedding_dim=EMBEDDING_DIM,
            catalog_items=len(news),
            built_at=datetime.now(UTC).isoformat(),
        )
    )

    from recommender.ranking.build_dataset import TRAIN_PATH
    from recommender.ranking.build_dataset import main as build_ranking_dataset

    build_ranking_dataset()
    ranking_model = train_ranking_model(pd.read_parquet(TRAIN_PATH))
    sio.dump(ranking_model, RANKING_MODEL_PATH)

    return {
        "catalog_items": len(news),
        "splits": ["train", "validation", "replay"],
        "impressions_per_split": NUM_IMPRESSIONS_PER_SPLIT,
        "retrieval_model": str(RETRIEVAL_MODEL_PATH),
        "ranking_model": str(RANKING_MODEL_PATH),
        "synthetic": True,
    }


def main() -> None:
    import json

    print(json.dumps(generate(), indent=2))


if __name__ == "__main__":
    main()
