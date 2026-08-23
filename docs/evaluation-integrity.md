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

## Real, unresolved finding: the popularity check does not reconfirm cleanly

The single-feature popularity AUC check does **not** reproduce the
original validation result. Measured with real, out-of-sample
popularity (recomputed from only the fit half of the tuning fold, to
avoid the exact in-sample leakage mechanism `docs/ranking-model.md`
itself names as the reason popularity looked artificially predictive
in the first place):

| | Original (validation) | Tune fold (out-of-sample popularity) |
|---|---|---|
| Popularity-alone AUC | 0.47 (worse than random) | **0.665** (clearly better than random) |

This is a real, reproducible discrepancy, not a bug in the
verification code — it held even after correcting an initial version
of this check that used in-sample popularity by mistake (see the
docstring in `verify_tuning_decisions.py` for that first, incorrect
attempt and why it was wrong). A plausible explanation, not yet
confirmed: `train` and the tune fold share the same 5-day window, where
item popularity may be genuinely stable enough within that single week
to predict clicks; `validation` is the very next day, where popularity
computed from the prior week may transfer far less cleanly if news
items are highly perishable. That would mean the original validation
measurement and this tune-fold measurement are both real, but are
measuring different things (next-day transfer vs. within-week
correlation), not that one of them is simply wrong.

**This finding is not resolved.** It does not overturn the original
decision to exclude `popularity` on its own — the original,
next-day-transfer measurement (AUC 0.47 on the actual day the model
would need to generalize to) is arguably the more relevant question for
a production model anyway — but it means the original decision's
justification ("popularity is uninformative") is not the full picture,
and the real underlying question (does popularity transfer to the very
next day, or does it only look useful within the same week it was
computed from) has not been definitively answered by either
measurement alone.

## What this means going forward

- The diversity cap and freshness threshold: genuinely reconfirmed by
  held-out data, not just validation. No further action needed.
- The popularity exclusion: the original decision may still be the
  right one for production use (next-day transfer is what actually
  matters), but the discrepancy above is a real, open question, not
  swept into either "confirmed" or "overturned." Documented here rather
  than resolved by picking whichever answer is more convenient.
