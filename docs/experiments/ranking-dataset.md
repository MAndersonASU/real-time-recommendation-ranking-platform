# Ranking Training Data

Runs the six ranking features (`docs/experiments/ranking-features.md`) over real data
and persists the result as two tables a classifier can be fit and
evaluated on. Implementation: `src/recommender/ranking/build_dataset.py`.

## What gets built

One row per (impression, candidate) pair, for both `train` and
`validation` (`docs/experiments/splits.md`), using popularity counts, a TF-IDF
vocabulary, and catalog embeddings fit only once — on `train` — and reused
unchanged for validation feature-building, the same discipline already
applied to every baseline. The label is MIND's own click/no-click
flag, already present in the exploded impression data.

No separate negative sampling was added on top of MIND's own candidates,
unlike retrieval's training data (`docs/experiments/retrieval-model.md`). Retrieval had
to judge the full 51,282-item catalog, so its in-impression negatives alone
were too narrow a signal on their own. Ranking only ever scores the
candidate list an impression already narrowed things down to, and that list
already contains a real mix of clicked and not-clicked items — adding
synthetic negatives here would solve a problem this check doesn't have.

Saved to `data/processed/mind_small/ranking/train.parquet` and
`validation.parquet` (both gitignored, reproducible via
`python -m recommender.ranking.build_dataset`).

## Results

| | Train | Validation |
|---|---|---|
| Rows | 4,621,015 | 1,222,429 |
| Positive rate | 4.10% | 3.83% |

Elapsed: 4m27s locally (CPU only).

Both counts and rates check out against evidence already on record rather
than being trusted on their own: the train row count (4,621,015) matches
the two-tower model's own in-impression training set size exactly
(`docs/experiments/retrieval-model.md`), and both positive rates land close to the
overall ~4% click-through rate already measured during data-quality work.
A hand spot-check of one real validation impression — recomputing hour of
day, history length, and category match directly from the raw behaviors
and catalog tables — matched the built table's values exactly across all
40 of that impression's candidate rows.
