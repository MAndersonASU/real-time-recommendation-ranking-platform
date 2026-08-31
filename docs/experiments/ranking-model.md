# Ranking model

The feature table contains six values, with five
used by the trained model. The model is logistic regression so its
weights and probabilities can be inspected directly.

Implementation: `src/recommender/ranking/train.py`.

## Model design

- A `StandardScaler` fitted only on `train` puts the five model inputs
  on comparable numeric scales.
- Plain logistic regression preserves the real click base rate.
- `class_weight="balanced"` is not used because it would change the
  probability scale and make calibration harder to interpret.

## Why popularity is excluded

The first fit used all six computed values:

| Measure | Train | Validation |
|---|---|---|
| AUC | 0.7185 | 0.5654 |

Individual feature checks identified the problem:

| Feature alone | Train AUC | Validation AUC |
|---|---|---|
| `popularity` | 0.6683 | 0.4719 |
| `content_similarity` | 0.5865 | 0.5894 |
| `retrieval_score` | 0.6478 | 0.6232 |

Popularity performed worse than chance on validation. Two measured
properties explain the mismatch:

- only 1,791 of 6,144 validation candidate articles (29.2%) had any
  training click; and
- well-represented training articles appeared about 272 times on
  average, so aggregate click count was unusually close to labels in
  the same training rows.

Fast news turnover makes old popularity unreliable for many next-day
articles. `popularity` remains in the saved feature table for analysis
but is not in `MODEL_FEATURE_COLUMNS`.

## Final result

The model was refitted with five inputs.

| | Train | Validation |
|---|---|---|
| Log loss | 0.1651 | 0.1577 |
| AUC | 0.6582 | 0.6382 |

The smaller train-validation gap is consistent with removing the
misleading popularity value.

| Feature | Coefficient |
|---|---|
| retrieval_score | 0.4098 |
| content_similarity | 0.1493 |
| user_history_length | 0.0486 |
| category_match | 0.0044 |
| hour_of_day | -0.0170 |

`retrieval_score` and `content_similarity` carry most of the model
weight. `category_match` is near zero, which is reasonable because it is
a coarser version of the other content signals. `hour_of_day` is a small
context value.

## Saved model and reproducibility

The model is written to:

```text
data/processed/mind_small/ranking_model.skops
```

Build it with:

```bash
python -m recommender.ranking.train
```

Training takes under 10 seconds locally.

The project uses `skops` instead of pickle-based `joblib` to avoid
loading arbitrary executable objects from a model file.

`skops.io.dump` does not produce identical bytes on every save. Two
fits from the same data have identical coefficients and intercepts but
different file hashes. A manifest's `ranking_model_sha256` therefore
checks one file's integrity; it does not by itself show that fitted
coefficients changed.

Catalog, split, content, and two-tower artifacts do rebuild to identical
bytes.
