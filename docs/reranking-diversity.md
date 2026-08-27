# Diversity Reranking

The first reranking policy: a slate-level decision layer, separating "how
relevant is this item" (the ranking model, the ranking model) from "is this the
right slate to show, as a set" (this check and the next).
Implementation: `src/recommender/reranking/diversity.py`.

## Measured before building anything

Rather than pick a category cap or similarity threshold by guesswork, the
naive ranked top-10 (the ranking model's own output, unchanged) was measured directly
across 3,000 real validation impressions:

- **53.1%** of slates already carry 4 or more items from a single
  category; **4.6%** are a single category for all 10 items.
- Pairwise TF-IDF cosine similarity among items *within* a naive top-10 is
  low overall (mean 0.017, median 0.0), with a thin tail: only **~0.25%**
  of pairs reach 0.5 or higher, and ~0.12% reach 0.7 or higher.

These two numbers point in different directions: category dominance is a
widespread, common property of the current ranked slate; near-exact
content duplication is real but genuinely rare in this corpus. The policy
below is sized accordingly — a category cap does most of the real work; a
near-duplicate similarity check (threshold 0.5, chosen from the measured
distribution above — well above the 95th percentile of ordinary same-slate
pairs, so it rarely misfires on merely-related content) is a real but
secondary safeguard.

## The policy

`build_diverse_slate` walks the ranking model's own score order and builds
a k-item slate in one constrained pass, then (if needed) a second,
unconstrained pass:

1. Sort all candidates by ranking score, descending — the ranking model's ordering,
   untouched at this point.
2. Add each candidate to the slate in that order, skipping it if its
   category has already reached a cap of 3 items in the slate, or if it's
   a near-duplicate (TF-IDF cosine similarity ≥ 0.5) of an item already
   selected.
3. If the constrained pass leaves the slate short of k items — possible
   when very few categories are present among the candidates at all — a
   second pass fills the remaining slots by score alone, ignoring both
   constraints. A slate short of k items is a worse outcome than a
   slightly less diverse full one, so the constraints reorder the slate;
   they never shrink it.

Every rule could be explained out loud in one sentence —
the "transparent slate-level logic" the design calls for, in contrast to a
learned reranking model whose behavior would need to be reverse-engineered
case by case.

Verified with 4 targeted tests (`tests/test_diversity.py`): the category
cap actually blocks excess same-category items in the constrained pass; a
deliberately exact-duplicate pair gets suppressed even when the category
cap alone would have allowed both; the relaxed fill pass genuinely
guarantees k items when the constrained pass alone would underfill; and
the slate never claims more items than actually exist among the
candidates.
