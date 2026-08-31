# Frozen evaluation protocol

This protocol was locked on August 18, 2026, after the three baselines
had been measured. Changing it would create a new protocol and require
all baselines to be rerun.

## Fixed settings

| Item | Rule |
|---|---|
| Evaluation split | `validation`: 30,270 impressions from November 14, 2019 |
| Top-K value | K = 10 |
| Metrics | Hit rate, Recall, NDCG, reciprocal rank (MRR), and catalog coverage |
| Coverage catalog | 51,282 rows in the training catalog |
| Baseline candidates | The items in each MIND `impressions` row |

Metric implementations live in
`src/recommender/evaluation/metrics.py` and are checked with a worked
example in `tests/test_metrics.py`.

The candidate rule applies only to baseline ranking. Retrieval
evaluation generates candidates from the full catalog and therefore
uses its own documented protocol.

## Split corrections and limits

The validation split was never used for gradient-based training.
However, early work used it to choose whether to drop `popularity` and
to choose diversity and freshness settings. Results on this split are
therefore development evidence, not untouched final estimates.

Later decisions use a tuning fold carved from `train`. See
[evaluation integrity](evaluation-integrity.md) and
[data splits](splits.md).

The `replay` split from November 15, 2019 has already been used for
streaming replay evaluation. It has not been used for gradient training
or for choosing a setting later reported against it, but it is not
unused. See [replay evaluation](replay-evaluation.md).

## How the contract is enforced

`src/recommender/evaluation/contract.py` owns the split paths, catalog
path, and `TOP_K` value used by evaluation commands.
`tests/test_contract.py` checks those fixed values. Moving baseline code
to this shared contract did not change its published results.

## Results under this protocol

The table below uses K=10 and the same 30,270 validation impressions.

| | Popularity | Content similarity | Collaborative |
|---|---|---|---|
| Hit rate | 0.5697 | 0.6557 | 0.5709 |
| NDCG | 0.2830 | 0.3526 | 0.2847 |
| Catalog coverage | 0.0370 | 0.0722 | 0.0389 |

Full context is in [baselines](baselines.md).

## Changes that require a new protocol

A new version and a complete baseline rerun are required if any of the
following changes:

- K;
- the evaluation split;
- the candidate definition; or
- a metric definition.

Do not silently change this page or `contract.py` around existing
numbers.
