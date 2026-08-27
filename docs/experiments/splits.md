# Time-Aware Splits

Three partitions, ordered strictly by time — never by random shuffling —
enforced by an explicit assertion (`assert_no_time_leakage`,
`src/recommender/data/splits.py`) rather than left to be correct by
construction alone.

| Split | Source | Date range | Rows | Use |
|---|---|---|---|---|
| `train` | MIND-small official train, first 5 days | 2019-11-09 → 2019-11-13 | 126,695 | Model fitting (the baselines through reranking) |
| `validation` | MIND-small official train, last day | 2019-11-14 | 30,270 | Model selection / tuning (the baselines through reranking) |
| `replay` | MIND-small official dev window | 2019-11-15 | 73,152 | Streaming replay and replay evaluation |

`train` and `validation` are carved from the official train window by a
single chronological cutoff — the last day becomes validation, the rest is
train. `replay` is MIND's own official dev window, used as-is. Nothing trains,
tunes or selects a model against it, but it is no longer untouched:
streaming replay and replay evaluation have both run against it.

Row counts are internally consistent by construction: `train` (126,695) +
`validation` (30,270) = 156,965, the exact row count of the ingested
official train split; `replay` (73,152) exactly matches the original
official dev split.

## Leakage check

`assert_no_time_leakage(train, validation, replay)` verifies each split's
maximum timestamp is strictly before the next split's minimum timestamp.
Verified on the real data: this passes silently (no exception) for the
partition above. A regression test (`tests/test_splits.py`) exercises the
same assertion against synthetic data — including a deliberately
overlapping pair of splits, to confirm the check actually fails when it
should, not just when it happens to.

## Why not fold `replay` into validation

Doing so would mean the streaming pipeline's "streaming replay" secretly re-processes
data a model was already tuned against, and replay evaluation's evaluation would no
longer be measuring performance on genuinely unseen data. The whole value
of a held-out replay set depends on nothing earlier having touched it.
