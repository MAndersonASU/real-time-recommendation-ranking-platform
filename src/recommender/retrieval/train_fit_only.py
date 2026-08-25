"""A retrieval model trained on the fit half alone, for tuning evidence.

The problem this exists to fix: tuning decisions (the diversity cap, the
freshness quota, the retrieval depth) are checked on a tuning fold carved
out of `train`, and the ranking model is refit on the fit half so it
never sees that fold's labels. But one of the features those decisions
are scored on is `retrieval_score`, and the retrieval model producing it
was trained on all of `train` -- including the tuning fold. So the fold
was held out from one model and not from the other, and every tuning
comparison carried that residual leakage.

This module trains a second retrieval model on fit-half impressions only.
It is deliberately a **separate bundle**, written to its own paths:

- `two_tower_model_fit_only.pt`
- `item_content_fit_only.npz`
- `bundle_fit_only.json`

Nothing here touches the deployed artifacts. Swapping the fit-half model
into serving would be the wrong trade -- it is trained on 80% of the data
specifically so it can be honest about a fold, which makes it a worse
model, not a better one. The deployed model stays the full-data one; this
one exists to say how much of the tuning evidence the leakage could
account for.

Run it before `verify_tuning_decisions`, on a machine holding the
licensed dataset:

    python -m recommender.retrieval.train_fit_only
"""

import json
import time
from datetime import UTC, datetime

import torch

from recommender.evaluation.contract import CATALOG_PATH, load_catalog, load_split
from recommender.evaluation.tuning_fold import TUNE_FOLD_SEED, split_train_for_tuning
from recommender.paths import mind_small_path
from recommender.retrieval.bundle import build_manifest, write_manifest
from recommender.retrieval.features import CONTENT_DIM
from recommender.retrieval.train import (
    BATCH_SIZE,
    EMBEDDING_DIM,
    NUM_SAMPLED_NEGATIVES,
    TRAIN_SEED,
    build_train_dataset,
    train_model,
)

FIT_ONLY_MODEL_PATH = mind_small_path("two_tower_model_fit_only.pt")
FIT_ONLY_CONTENT_PATH = mind_small_path("item_content_fit_only.npz")
FIT_ONLY_BUNDLE_PATH = mind_small_path("bundle_fit_only.json")
FIT_ONLY_REPORT_PATH = mind_small_path("two_tower_fit_only_train_report.json")

# Matched to the deployed model's budget so the two are comparable. A
# fit-half model trained for longer or shorter would confound the
# leakage question with a training-budget difference.
DEFAULT_MAX_STEPS = 6000


def build_fit_only_dataset(num_sampled_negatives: int = NUM_SAMPLED_NEGATIVES):
    """The same dataset construction as the deployed model's, restricted
    to fit-half impressions.

    Uses the identical `split_train_for_tuning` seed the tuning fold
    itself uses, so "fit half" means the same rows in both places. A
    different seed here would produce a model that had still seen part
    of the fold it is meant to be blind to, which is the whole defect.
    """
    train = load_split("train")
    fit_rows, _tune_rows = split_train_for_tuning(train)
    return build_train_dataset(
        num_sampled_negatives=num_sampled_negatives,
        train=fit_rows,
        content_artifact_path=FIT_ONLY_CONTENT_PATH,
    ), len(fit_rows), len(train)


def main(max_steps: int = DEFAULT_MAX_STEPS) -> None:
    (dataset, num_categories, num_subcategories), fit_impressions, all_impressions = (
        build_fit_only_dataset()
    )
    print(
        f"fit-half dataset: {len(dataset)} examples from {fit_impressions} of "
        f"{all_impressions} training impressions"
    )

    start = time.time()
    model, losses, checkpoints = train_model(
        max_steps,
        dataset=dataset,
        num_categories=num_categories,
        num_subcategories=num_subcategories,
    )
    elapsed = time.time() - start

    torch.save(model.state_dict(), FIT_ONLY_MODEL_PATH)

    news = load_catalog()
    write_manifest(
        build_manifest(
            retrieval_model_path=FIT_ONLY_MODEL_PATH,
            content_artifact_path=FIT_ONLY_CONTENT_PATH,
            catalog_path=CATALOG_PATH,
            content_dim=CONTENT_DIM,
            embedding_dim=EMBEDDING_DIM,
            catalog_items=len(news),
            built_at=datetime.now(UTC).isoformat(),
        ),
        path=FIT_ONLY_BUNDLE_PATH,
    )

    report = {
        "bundle": "tuning_fit_only",
        "purpose": (
            "leakage-free retrieval scores for tuning comparisons; not a serving "
            "artifact and never loaded by the serving path"
        ),
        "tune_fold_seed": TUNE_FOLD_SEED,
        "fit_impressions": fit_impressions,
        "all_train_impressions": all_impressions,
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
    }
    FIT_ONLY_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
