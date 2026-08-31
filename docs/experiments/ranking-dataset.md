# Ranking dataset

This command turns MIND impressions into labeled rows for ranking.
Implementation: `src/recommender/ranking/build_dataset.py`.

## What gets built

Each row represents one impression-candidate pair. The label is MIND's
existing click/no-click value.

The build creates both training and validation tables. Popularity
counts, the TF-IDF vocabulary, and catalog embeddings are fitted only on
`train`, then reused unchanged for validation.

The feature builder produces the six values described in
[ranking features](ranking-features.md). The final trained model uses
five after the popularity ablation.

## Why there are no sampled negatives

Ranking scores only the candidates already present in one MIND
impression. That list contains clicked and not-clicked items, so it
already supplies negatives.

Retrieval has a different job: it searches the full 51,282-item catalog
and therefore adds sampled catalog negatives. See the
[retrieval model](retrieval-model.md).

## Output

The generated files are ignored by Git:

- `data/processed/mind_small/ranking/train.parquet`
- `data/processed/mind_small/ranking/validation.parquet`

Build them with:

```bash
python -m recommender.ranking.build_dataset
```

## Results

| | Train | Validation |
|---|---|---|
| Rows | 4,621,015 | 1,222,429 |
| Positive rate | 4.10% | 3.83% |

Elapsed time was 4 minutes 27 seconds on a local CPU.

The 4,621,015 training rows match the two-tower model's in-impression
training count. Both positive rates are consistent with the roughly 4%
click rate in the [data-quality profile](data-quality.md).

A manual check recomputed hour, history length, and category match for
one real validation impression. All 40 candidate rows matched the built
table.
