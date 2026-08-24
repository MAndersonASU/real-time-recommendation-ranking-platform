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

## Comparing against real alternatives, not just the chosen value's own behavior

The diversity check's own "naive top-10" scores now come from a
ranking model refit on the fit half of the tuning fold only — never
seeing these tuning rows at all, unlike an earlier version of this
check, which reused the already-trained production model (fit on *all*
of `train`, including these same rows).

Both checks also now compare the currently-configured value against
real alternatives, run through the actual production algorithm
(`build_diverse_slate`, `apply_freshness_quota`), with a selection rule
decided *before* looking at the resulting numbers
(`verify_diversity_cap`, `verify_freshness_threshold` in
`verify_tuning_decisions.py`).

**Freshness: the predefined rule worked as intended, and reconfirms
the configured threshold.** Rule: choose the smallest threshold whose
zero-fresh-impression rate stays under 5%.

| Threshold (days) | Fresh-row rate | Zero-fresh-impression rate |
|---|---|---|
| 0.25 | 12.2% | 23.5% |
| **0.5 (configured)** | **32.3%** | **3.4%** |
| 1.0 | 73.0% | 0.1% |
| 2.0 | 88.5% | ~0.0% |
| 7.0 | 100% | 0.0% |

0.5 days is the smallest threshold clearing the 5% bar — the rule
selects exactly the currently-configured value.

**Diversity: the predefined rule does not work as intended, and that
is reported honestly rather than papered over.** Rule as written:
choose the smallest cap reaching at least 90% of the *uncapped* mean
distinct-category count.

| Cap | Mean slate relevance | Mean distinct categories |
|---|---|---|
| 1 | 0.438 | 7.59 |
| 2 | 0.482 | 5.64 |
| **3 (configured)** | **0.507** | **4.96** |
| 5 | 0.530 | 4.42 |
| No cap | 0.546 | 4.05 |

Because a smaller cap can only ever *increase* diversity relative to no
cap, every candidate value clears a bar set relative to the *worst*
(uncapped) case — the rule trivially selects the smallest cap tried
(1), regardless of the real tradeoff. That is a flaw in this specific
rule's design, not evidence that cap=1 is actually better than cap=3:
a meaningful rule would need to weigh relevance loss against diversity
gain jointly (e.g. a fixed relevance budget), which this rule does not
do. The real, useful output here is the tradeoff table itself — cap=3
gives up about 7% mean relevance versus no cap in exchange for roughly
22% more distinct categories per slate — not the rule's own selected
value. Choosing among these values is a real product tradeoff this
project has not made via a formal decision procedure; cap=3 remains a
disclosed, reasonable choice within the measured tradeoff space, not
something this comparison proves optimal or proves wrong.

## What this means going forward

- The freshness threshold: reconfirmed twice now — once by held-out
  coverage at the chosen value, once by a predefined rule comparing
  real alternatives that independently selects the same value.
- The diversity cap: the chosen value's own held-out behavior
  reconfirmed cleanly, and a real relevance/diversity tradeoff curve
  across alternatives now exists and is reported honestly — but no
  rule tested here actually settles which cap value is "best," a real,
  disclosed, still-open question distinct from whether cap=3's own
  measured behavior is real (it is).
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
