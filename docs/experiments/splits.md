# Time-based data splits

The project uses three chronological partitions. It does not shuffle
rows randomly across dates.

| Split | Source | Date range | Rows | Use |
|---|---|---|---|---|
| `train` | MIND-small official train, first 5 days | 2019-11-09 → 2019-11-13 | 126,695 | Model fitting (the baselines through reranking) |
| `validation` | MIND-small official train, last day | 2019-11-14 | 30,270 | Model selection / tuning (the baselines through reranking) |
| `replay` | MIND-small official dev window | 2019-11-15 | 73,152 | Streaming replay and replay evaluation |

The last day of the official training window becomes `validation`; the
earlier days become `train`. The official development window becomes
`replay` without modification.

The counts reconcile:

- `126,695 + 30,270 = 156,965`, the official training-window total; and
- `73,152` matches the official development-window total.

No model is fitted or selected with `replay`. The split is not unused:
streaming replay and replay evaluation have both run against it.

## Leakage check

`assert_no_time_leakage(train, validation, replay)` requires the latest
timestamp in one partition to precede the earliest timestamp in the
next. The real data passes this check.

`tests/test_splits.py` also supplies overlapping synthetic partitions
and confirms that the guard rejects them.

## Why not fold `replay` into validation

Combining `replay` with `validation` would make the streaming replay use
data that already influenced model selection. Keeping it separate means
the replay data did not fit or select a model, even though it has been
used for replay evaluation.
