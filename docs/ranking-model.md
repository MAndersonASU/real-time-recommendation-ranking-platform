# Ranking Model

Phase 4's first ranking model, over the six features defined in
`docs/ranking-features.md`. Deliberately not a neural model at this
stage — logistic regression, so every fitted weight can be read and
sanity-checked directly rather than inferred from behavior alone.
Implementation: `src/recommender/ranking/train.py`.

## Architecture

- Features are standardized (`StandardScaler`, fit on `train` only) before
  fitting, since the six features live on very different numeric scales —
  without it, a feature's fitted weight would partly reflect its units
  rather than its real importance.
- Plain (unweighted) logistic regression, not `class_weight="balanced"`.
  Balancing would improve class separation but distort predicted
  probabilities away from the real ~4% base rate, and honest probabilities
  are exactly what a calibration check needs.

## A feature that measured worse than useless, found before trusting the result

The first fit, using all six features, showed a striking train/validation
gap: AUC 0.7185 on `train`, 0.5654 on `validation` — barely above chance.
Rather than accept that as "the model overfits" without a cause, each
feature was checked in isolation. `popularity` alone scored AUC 0.6683 on
`train` but **0.4719 on validation — worse than random guessing**. Every
other feature generalized normally (`content_similarity` alone: 0.5865 →
0.5894; `retrieval_score` alone: 0.6478 → 0.6232).

Two compounding causes, both checked directly rather than assumed:

- Only 1,791 of 6,144 distinct validation candidate items (29.2%) have any
  nonzero training click count at all — the exact same cold-start figure
  already found for the collaborative-filtering baseline
  (`docs/baselines.md`). News articles churn fast enough that most of any
  given day's candidates weren't old enough during training to have
  accumulated click history.
- `popularity` is an aggregate click count over items that repeat, on
  average, 272 times in `train`'s own exploded impression rows — so for
  well-represented items, the feature partly correlates with the very
  labels it's fit to predict, inflating its apparent value within `train`
  in a way that doesn't transfer to a later, different set of candidates.

`popularity` was dropped from the trained model on this evidence (kept in
the persisted feature table for transparency, excluded via
`MODEL_FEATURE_COLUMNS` in `train.py`). Refit on the remaining five
features:

## Real result (five features, popularity excluded)

| | Train | Validation |
|---|---|---|
| Log loss | 0.1651 | 0.1577 |
| AUC | 0.6582 | 0.6382 |

A small, expected train/validation gap this time, not a large unexplained
one — evidence the fix addressed the actual cause rather than just hiding
a symptom.

| Feature | Coefficient |
|---|---|
| retrieval_score | 0.4098 |
| content_similarity | 0.1493 |
| user_history_length | 0.0486 |
| category_match | 0.0044 |
| hour_of_day | -0.0170 |

Every sign is sensible: `retrieval_score` and `content_similarity` (both
genuine personalization signals) carry the most weight; `category_match`
lands near zero, consistent with it being a coarser version of the same
signal `content_similarity` and `retrieval_score` already capture more
precisely; `hour_of_day` is small and slightly negative, appropriate for
what was always expected to be a weak contextual feature.

Model saved to `data/processed/mind_small/ranking_model.skops` (gitignored,
reproducible via `python -m recommender.ranking.train`) — skops, not joblib:
joblib is a thin wrapper over pickle, so loading it means executing
arbitrary code embedded in the file; skops serializes and reloads the same
trained Pipeline without that risk. Elapsed: under 10
seconds locally — logistic regression over 5 features and 4.6M rows is
fast compared to the two-tower model's training run.
