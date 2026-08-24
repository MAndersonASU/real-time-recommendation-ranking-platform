# Held-Out Evaluation Integrity

Three feature and hyperparameter decisions in this project were
originally chosen by looking at measurements on `validation`, which
was then also used for every final reported metric in
`docs/baselines.md`, `docs/ranking-model.md`,
`docs/reranking-evaluation.md`, and `docs/conclusions.md`. This is
model/hyperparameter-selection leakage: even though no gradient-based
training ever touched validation directly, a decision informed by
looking at validation and then reported against that same validation
is not a genuinely held-out result. `docs/evaluation-protocol.md`'s own
claim that validation is "never used for training or tuning by any
model evaluated against it" was false for these three decisions, and
has been corrected.

## The three decisions

- **Dropping `popularity` from the ranking model's features**
  (`src/recommender/ranking/train.py`) — originally justified by a
  single-feature AUC check on validation (0.47, worse than random).
- **The diversity category cap (3 items per category)**
  (`src/recommender/reranking/diversity.py`) — originally chosen after
  measuring that 53.1% of naive top-10 slates on validation already
  carried 4+ items from one category.
- **The freshness threshold (12 hours) and minimum fresh count (2)**
  (`src/recommender/reranking/freshness.py`) — originally chosen after
  measuring that 36.3% of validation candidate rows were fresh at that
  threshold, with only 0.7% of impressions having zero fresh candidates.

## The fix: a held-out tuning fold, disjoint from validation by construction

`src/recommender/evaluation/tuning_fold.py` carves a deterministic,
seeded fold from `train`'s own rows, split by `impression_id` so one
impression's candidates never span both halves. Any future feature or
hyperparameter decision should be checked against this fold — never
against `validation`, which is reserved for final reporting only, from
this point forward. `src/recommender/evaluation/
verify_tuning_decisions.py` re-runs the same three original
measurements against this fold instead of validation.

This does not retroactively change what the already-reported numbers
in `docs/baselines.md` and elsewhere measure — those numbers are what
they are, computed under the conditions actually used. What changes is
that any future decision has real, disjoint, held-out infrastructure to
use instead of reaching for validation again.

## Real result: two of three decisions independently reconfirmed

| Decision | Original (validation) | Tune fold | Confirmed? |
|---|---|---|---|
| Diversity: 4+ same-category rate | 53.1% | 59.6% | Yes — same order of magnitude, same conclusion |
| Diversity: single-category rate | 4.6% | 7.4% | Yes |
| Freshness: fresh-row rate at 12h | 36.3% | 32.3% | Yes — same order of magnitude |
| Freshness: zero-fresh-impression rate | 0.7% | 3.4% | Yes — still rare, same conclusion |

Both the diversity cap and the freshness threshold hold up under a
genuinely disjoint, held-out re-check. The original decisions were not
simply noise fit to validation.

## Real finding: evidence supports a recency-leakage explanation for the popularity discrepancy

An earlier version of this document reported the single-feature
popularity AUC check as a real, unresolved discrepancy. Measured with
real, out-of-sample popularity (recomputed from only the fit half of
the tuning fold, to avoid the exact in-sample leakage mechanism
`docs/ranking-model.md` itself names as the reason popularity looked
artificially predictive in the first place):

| | Original (validation) | Random-split tune fold |
|---|---|---|
| Popularity-alone AUC | 0.47 (worse than random) | 0.665 (clearly better than random) |

This held even after correcting an initial version of this check that
used in-sample popularity by mistake (see the docstring in
`verify_tuning_decisions.py` for that first, incorrect attempt and why
it was wrong). The remaining, plausible explanation: `split_train_for_
tuning` splits `train`'s own rows *randomly* by impression_id, so a
"fit" impression and a "tune" impression can sit right next to each
other in real time — letting short-term popularity recency (an item
hot this hour is usually still hot next hour) leak across the split in
a way the real `validation` split (a separate, later day) never could.

**Directly tested, not left as a hypothesis.**
`chronological_tuning_split_impression_ids`
(`src/recommender/evaluation/tuning_fold.py`) carves the same kind of
fold by real chronological order instead — the earliest 80% of train's
impressions become `fit`, the most recent 20% become `tune` — giving
`tune` the same kind of real temporal gap from `fit` that `validation`
has from `train`. Re-running the identical out-of-sample popularity
check against this chronological split
(`verify_popularity_exclusion_with_temporal_split` in
`verify_tuning_decisions.py`):

| | Original (validation) | Random-split tune fold | Chronological-split tune fold |
|---|---|---|---|
| Popularity-alone AUC | 0.47 | 0.665 | **0.489** |

The chronological split's AUC (0.489) lands close to the original
validation result (0.47) — this result supports the recency-leakage
hypothesis, not a controlled experiment that isolates recency as the
sole variable (fit and tune also differ in which users and impressions
land on each side of a chronological boundary versus a random one, a
real confound this check does not separately rule out). It is real
evidence in favor of that explanation, not proof of it.

**A separate, larger gap this section does not close**: this check —
and the diversity/freshness checks above — measure the *chosen*
hyperparameter value's own behavior on held-out data. None of the
three compare the chosen value against real alternatives (no diversity
cap at all, other cap values; other freshness thresholds and minimum
counts), and the diversity check's own "naive top-10" scores come from
the ranking model as currently trained — on all of `train`, including
these tuning rows, not refit without them. A held-out re-measurement of
one already-chosen value is weaker evidence than an actual comparison
across candidate values decided in advance. That comparison has not
been done yet.

## What this means going forward

- The diversity cap and freshness threshold: the *chosen* values'
  behavior held up on held-out data, not just validation — real
  evidence, but not a comparison against alternative values, and not
  yet a closed question (see the gap above).
- The popularity exclusion: the original decision to exclude
  `popularity` (AUC 0.47, no better than random on genuinely
  out-of-sample, temporally-realistic data) is supported, not proven,
  by the chronological-split re-check. The earlier discrepancy has a
  real, evidence-backed explanation now, not just a disclosed
  correlation: it is consistent with `split_train_for_tuning`'s random
  split letting recency leak across the fold boundary, a hypothesis a
  chronological re-check now supports rather than one left as an
  untested assumption. No model change made.
- `split_train_for_tuning`'s random-by-impression_id split remains the
  right default for the diversity and freshness checks above (both
  reconfirmed cleanly under it, and neither has any reason to be
  sensitive to short-term recency the way popularity is) —
  `chronological_tuning_split_impression_ids` is a second, deliberately
  different tool for exactly this kind of recency-sensitive question,
  not a replacement.
