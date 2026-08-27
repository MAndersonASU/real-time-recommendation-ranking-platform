# Held-Out Evaluation Integrity

Three feature and hyperparameter decisions in this project were
originally chosen by looking at measurements on `validation`, which
was then also used for every final reported metric in
`docs/experiments/baselines.md`, `docs/experiments/ranking-model.md`,
`docs/experiments/reranking-evaluation.md`, and `docs/conclusions.md`. This is
model/hyperparameter-selection leakage: even though no gradient-based
training ever touched validation directly, a decision informed by
looking at validation and then reported against that same validation
is not a genuinely held-out result. `docs/experiments/evaluation-protocol.md`'s own
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
against `validation`. Validation has already been used for selection, so
it is post-selection development evaluation rather than an untouched
final estimate; no untouched final split remains.
`src/recommender/evaluation/verify_tuning_decisions.py` re-runs the same
three original measurements against this fold instead of validation.

This does not retroactively change what the already-reported numbers
in `docs/experiments/baselines.md` and elsewhere measure — those numbers are what
they are, computed under the conditions actually used. What changes is
that any future decision has real, disjoint, held-out infrastructure to
use instead of reaching for validation again.

## Results: two of three decisions independently reconfirmed

| Decision | Original (validation) | Tune fold | Confirmed? |
|---|---|---|---|
| Diversity: 4+ same-category rate | 53.1% | 59.6% | Yes — same order of magnitude, same conclusion |
| Diversity: single-category rate | 4.6% | 7.4% | Yes |
| Freshness: fresh-row rate at 12h | 36.3% | 32.3% | Yes — same order of magnitude |
| Freshness: zero-fresh-impression rate | 0.7% | 3.4% | Yes — still rare, same conclusion |

Both the diversity cap and the freshness threshold hold up under a
genuinely disjoint, held-out re-check. The original decisions were not
simply noise fit to validation.

## finding: evidence supports a recency-leakage explanation for the popularity discrepancy

An earlier version of this document reported the single-feature
popularity AUC check as a real, unresolved discrepancy. Measured with
real, out-of-sample popularity (recomputed from only the fit half of
the tuning fold, to avoid the exact in-sample leakage mechanism
`docs/experiments/ranking-model.md` itself names as the reason popularity looked
artificially predictive in the first place):

| | Original (validation) | Random-split tune fold |
|---|---|---|
| Popularity-alone AUC | 0.47 (worse than random) | 0.665 (clearly better than random) |

This held even after correcting an initial version of this check that
used in-sample popularity by mistake (see the docstring in
`verify_tuning_decisions.py` for that first, incorrect attempt and why
it was wrong). The remaining, plausible explanation: `split_train_for_tuning` splits `train`'s own rows *randomly* by impression_id, so a
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
real confound this check does not separately rule out). It is evidence in favor of that explanation, not proof of it.

## Comparing against real alternatives, not just the chosen value's own behavior

The diversity check's own "naive top-10" scores now come from a
ranking model refit on the fit half of the tuning fold only — never
seeing these tuning rows at all, unlike an earlier version of this
check, which reused the already-trained serving-path model (fit on *all*
of `train`, including these same rows).

Both checks also now compare the currently-configured value against
real alternatives, run through the actual current ranking implementation
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

**Diversity: the first rule did not work, and the replacement does.**

The rule originally written here was: choose the smallest cap reaching
at least 90% of the *uncapped* mean distinct-category count. It could
not work, and that was reported rather than quietly patched. Slate
diversity rises monotonically as the cap falls, so a bar stated relative
to the uncapped (least diverse) case is cleared by every capped value —
the rule always selected the smallest cap tried, whatever it cost in
relevance, and so settled nothing.

The replacement bounds the cost instead of the benefit: among caps whose
mean slate relevance stays within a stated budget of the uncapped mean,
take the one with the highest mean distinct-category count. That is not
monotone-trivial, because an aggressive cap spends relevance to buy
diversity and a tight budget can rule it out.

Measured on the tuning fold:

Generated from [`reports/tuning-decisions.json`](../../reports/tuning-decisions.json).

| Cap | Mean slate relevance | Mean distinct categories |
|---|---|---|
| 1 | 0.498 | 7.52 |
| 2 | 0.552 | 5.69 |
| **3 (configured)** | **0.579** | **5.07** |
| 5 | 0.602 | 4.57 |
| No cap | 0.614 | 4.24 |

The rule's answer now genuinely depends on how much relevance a
diversity gain is judged to be worth:

| Relevance budget | Cap selected |
|---|---|
| 85% | 2 |
| 90% | **3 (the configured value)** |
| 95% | 5 |
| 99% | none affordable |

That spread is the point. The budget is a product decision, not
something this data can settle, and fixing a single value after seeing
the table would be exactly the post-hoc rule-fitting this document
exists to prevent. What can be said honestly: cap=3 is the choice a 90%
relevance budget produces, it sits mid-range in a measured
tradeoff, and nothing here shows it to be wrong.

**Retrieval depth: a change, decided on the tuning fold.**

Retrieval depth — how many candidates the serving path pulls from the
index before ranking — was 50 out of 51,282 items. Measured on the
tuning fold (`verify_retrieval_depth`):

Generated from [`reports/tuning-decisions.json`](../../reports/tuning-decisions.json).

| Depth | Clicked item reached the ranker | Search p99 |
|---|---|---|
| 50 (was configured) | 6.2% | 0.34 ms |
| 100 | 9.3% | 0.39 ms |
| 200 | 11.9% | 0.47 ms |
| 500 | 15.8% | 0.78 ms |
| **1000 (now configured)** | **21.5%** | **2.27 ms** |

Ranking cannot promote an item retrieval never surfaced, so this was a
hard ceiling on the whole pipeline.

A predefined search-latency budget was stated before these numbers were
produced — and it did not bind, since every depth came in under a
millisecond. A "deepest affordable" rule would therefore have
degenerated into "deepest tried", the same defect as the original
diversity rule, so it is not presented as having selected anything.
Index search is also not where depth actually costs: ranking and
reranking both scale with candidate count. Measured end to end,
depth 1,000 adds about 4 ms of p50 request latency over depth 50.

Depth 1,000 was therefore chosen as a judgment call from a measured
tradeoff — roughly 3.6x more clicked items reaching the ranker for about
4 ms — not as the output of a rule. It was measured on the tuning fold
specifically because deciding it on `validation` and then reporting
against `validation` is the exact mistake this document records.

## What this means going forward

- **The freshness threshold**: reconfirmed twice — once by held-out
  coverage at the chosen value, once by a predefined rule comparing real
  alternatives that independently selects the same value.
- **The diversity cap**: the flawed rule was replaced by a
  relevance-budget rule that genuinely discriminates between cap values.
  cap=3 is what a 90% relevance budget selects, and it sits mid-range in
 a measured tradeoff. The budget itself remains a product
  judgment, not something this data settles — which is a narrower and
  more honest claim than "reconfirmed".
- **Retrieval depth**: raised from 50 to 1,000 on tuning-fold evidence,
  roughly tripling how often the clicked item reaches the ranker for
  about 4 ms of end-to-end latency. Chosen as a judgment call from a
  measured tradeoff, since the predefined latency budget did not bind.
- **The popularity exclusion**: supported, not proven, by the
  chronological-split re-check. The earlier discrepancy is consistent
  with `split_train_for_tuning`'s random split letting recency leak
  across the fold boundary. A real confound remains — a chronological
  split also changes which users land on each side — so this is
  evidence for the explanation, not isolation of it. No model change
  made.
- **`split_train_for_tuning`'s random-by-impression_id split** remains
  the right default for the diversity and freshness checks (neither has
  reason to be sensitive to short-term recency the way popularity is);
  `chronological_tuning_split_impression_ids` is a second, deliberately
  different tool for recency-sensitive questions, not a replacement.

## The pattern worth naming

Two selection rules written for this document turned out not to
discriminate at all: both stated a bound on the *benefit* of a change
along an axis that moves monotonically with the parameter, so every
candidate value cleared the bar and the rule silently collapsed into
"pick the most extreme value tried."

The fix in both cases was to bound the **cost** instead — relevance lost
for diversity, latency spent for recall — because cost is what actually
trades off against the thing being maximized. A rule that cannot reject
any candidate is not a selection rule, and reporting one as though it
had chosen something would be worse than having no rule at all.
