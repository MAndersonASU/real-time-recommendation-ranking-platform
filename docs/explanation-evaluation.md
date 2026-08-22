# Evaluating Explanations Separately

Recommendation quality (hit rate, recall, NDCG, MRR) measures whether
the right item appeared in a slate. None of those numbers say anything
about whether an explanation attached to that item is honest or
useful — a different property, measured here with its own metrics,
never folded into the ranking numbers tracked since Phase 2.
Implementation: `src/recommender/evaluation/evaluate_explanations.py`.

## The real metrics

- **Refusal rate** — how often the system correctly declines to
  explain a recommendation for lack of real supporting evidence.
- **Faithfulness rate** — of the explanations actually shown, how many
  independently re-verify as containing the real evidence they claim,
  checked again from scratch rather than trusting the generation
  module's own gate to have worked.
- **Model-contribution rate** — of the explanations shown, how many
  are the local model's own rewrite versus the safe fallback template,
  the honest measure of how much the generative layer itself actually
  contributes.

## Real result, 60 real validation users, 180 real recommendations

| Metric | Value |
|---|---|
| Total recommendations evaluated | 180 |
| Refused (no supporting evidence) | 15 (8.3%) |
| Attempted explanations | 165 |
| **Faithfulness rate (independently re-verified)** | **100%** |
| Model rewrite used | 20 (12.1% of attempted) |
| Template fallback used | 145 (87.9% of attempted) |
| Mean explanation length | 54.2 characters |
| Distinct explanation strings | 9 |

## What this confirms, and what it discloses honestly

**Faithfulness held at 100% across a sample four times larger than the
earlier hand-checked sample** — the real, independent re-verification
here (a separate function, not a re-use of the generation module's own
gate) found no case where a shown explanation failed to contain the
evidence it claimed. This is a genuine confirmation the gate works,
not an assumption carried over from a smaller sample.

**The model's real, verified contribution is a minority of attempted
explanations (12.1%)**, consistent with the earlier smaller-sample
finding (2 of 14, ~14.3%) — the same real limitation, now confirmed at
four times the scale rather than resting on one small sample.

**Only 9 distinct explanation strings appeared across 165 attempted
explanations, a real and disclosed limitation**: since the fallback
template is built from category and content-similarity flags alone,
users who share a dominant category receive an identical sentence.
Explanations here are grounded and honest, but personalized only to
the same coarse category level the ranking model itself uses for
`category_match` — not to any finer-grained signal. A model contribution
rate this low means most of that repetition isn't currently broken up
by genuine model-authored variation either.
