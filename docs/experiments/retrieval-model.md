# Two-tower retrieval model

This page describes model structure and training. Quality results are in
the [retrieval evaluation](retrieval-evaluation.md).

Implementation: `src/recommender/retrieval/`.

## Model in plain language

| Part | Behavior |
|---|---|
| Item vector | Combines category, subcategory, and a 64-dimensional title-and-abstract vector, then projects to 32 dimensions |
| User vector | Averages the item vectors from the user's recent click history |
| History limit | 20 most recent articles |
| Score | User-item dot product plus one learned global bias |
| Labels | MIND clicks, shown-but-not-clicked items, and sampled catalog negatives |

The user tower has no separate parameter table. It derives a user vector
from the same item tower used to encode candidates.

The 20-item history limit keeps batches fixed in size. Training history
has a median length of 19, a 90th percentile of 77, and a maximum of
558.

## Why the global bias exists

The first full run used only a dot product. After one epoch and 2,257
optimization updates, loss stopped near 0.675.

That result was worse than a constant model. With about 4% positive
labels, always predicting the base rate gives binary cross-entropy near
0.168:

```text
-p ln(p) - (1-p) ln(1-p) ≈ 0.168
```

The embedding geometry had to learn both overall click rarity and
user-item differences. A single learned `global_bias` now represents the
base rate directly.

## Initial training run

The run used:

- 6,000 optimization updates;
- batch size 2,048;
- 32-dimensional embeddings;
- 4,621,015 training examples;
- about 1.3 passes over the training set; and
- 7 minutes 35 seconds on a local CPU.

| Update | Mean loss (last 500) |
|---|---|
| 500 | 0.6288 |
| 1,500 | 0.3437 |
| 3,000 | 0.2140 |
| 4,500 | 0.1774 |
| 6,000 | 0.1678 |

The final loss matches the 0.1679 base-rate entropy. This confirms that
the bias correction works; it does not prove that the embeddings rank
articles well. Ranking quality requires held-out metrics.

## Catalog negative sampling

Shown-but-not-clicked articles are difficult negatives from MIND's own
candidate list. Retrieval also needs to distinguish a clicked article
from the rest of the catalog.

Each positive therefore receives four uniformly sampled catalog
negatives. Sampling rejects an article that the same user clicked
elsewhere in `train`. Only training clicks are used for that check, so
validation and replay labels do not leak into training.

Relevant code:

- `build_catalog_arrays` and `build_user_clicked_rows` in `features.py`;
- `sample_negative_rows` and `sample_negatives_for_positives` in
  `negatives.py`; and
- `SampledNegativeDataset` in `dataset.py`.

## Training with catalog negatives

The comparison kept the same 6,000-update budget, batch size, and
embedding dimension.

The dataset grew from 4,621,015 to 5,379,091 examples:

```text
189,519 positive clicks × 4 negatives = 758,076 added rows
```

Elapsed time was 8 minutes 3 seconds on a local CPU.

| Update | Mean loss (last 500) |
|---|---|
| 500 | 0.6189 |
| 1,500 | 0.3366 |
| 3,000 | 0.2012 |
| 4,500 | 0.1609 |
| 6,000 | 0.1510 |

Positive prevalence fell from 4.04% to 3.52%, moving the matching
entropy floor to about 0.1525. Final loss was 0.1510. As above, this
shows stable training behavior, not recommendation quality by itself.

## Why article text was added

The original item tower used only category and subcategory. Those fields
produced 284 distinct vectors for 51,282 articles, so the model could
identify a topic but could not distinguish most articles within it.

The current tower builds a deterministic, row-normalized content vector
from title and abstract:

1. TF-IDF represents the text.
2. Seeded `TruncatedSVD` reduces it to 64 dimensions.
3. The model combines it with category and subcategory embeddings.

This representation is content-based, not article-ID-based. An article
without training clicks can still receive a vector from its text. A
fixed random seed makes the fitted basis reproducible.

Distinct catalog vectors increased from 284 to 50,704. In the retrieval
evaluation, the four relevance measures improved by 7.6–13.5× and
catalog coverage improved by 1.5×.

## Saved artifact

The model is written to:

```text
data/processed/mind_small/two_tower_model.pt
```

The file is ignored by Git. Rebuild it with:

```bash
python -m recommender.retrieval.train
```

Reload verification confirms that saved parameters match the trained
model exactly.
