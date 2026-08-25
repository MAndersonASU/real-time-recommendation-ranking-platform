# Evaluating Explanations Separately

Recommendation quality (hit rate, recall, NDCG, MRR) measures whether
the right item appeared in a slate. None of those numbers say anything
about whether an explanation attached to that item is honest or
useful — a different property, measured here with its own metrics,
never folded into the ranking numbers tracked since Phase 2.
Implementation: `src/recommender/evaluation/evaluate_explanations.py`.

## The metrics

- **Refusal rate** — how often the system correctly declines to
  explain a recommendation for lack of real supporting evidence.
- **Lexical-policy pass rate** — of the explanations actually shown, how many
  pass an independent check for containing the evidence they claim and
  no unsupported entity, actor, causal claim, guarantee, or
  personalization claim. "Independent" means a genuinely different
  check (a hand-curated blacklist of fabrication-indicator words) than
  the generation module's own gate (a closed-vocabulary whitelist), not
  a second copy of the same lexical assumption — an earlier version of
  this evaluation shared the production gate's exact design and
  therefore its exact blind spot (`docs/explanation-boundary.md`).
- **Model-contribution rate** — of the explanations shown, how many
  are the local model's own rewrite versus the safe fallback template,
  the honest measure of how much the generative layer itself actually
  contributes.

## Result, 60 real validation users, 180 real recommendations

Measured after the faithfulness gate was rebuilt as a closed-vocabulary
check (`docs/explanation-boundary.md`) — the model's rewrite must now
consist only of words already in the template plus a small, fixed set
of grammatical connectives, not just avoid unfamiliar capitalized words.

| Metric | Value |
|---|---|
| Total recommendations evaluated | 180 |
| Refused (no supporting evidence) | 15 (8.3%) |
| Attempted explanations | 165 |
| Lexical-policy pass rate | 100% (165/165) |
| Model rewrite used | 12 (7.3% of attempted) |
| Template fallback used | 153 (92.7% of attempted) |
| Mean explanation length | 55.1 characters |
| Distinct explanation strings | 9 |

## What this shows, and its real limitations

No violations were detected in this evaluated sample under the
documented checks — every one of the 165 attempted explanations passed
both the production gate and the independent, differently-designed
verification. That is a statement about this sample under these
checks, not a claim that no rewrite could ever slip through: the
blacklist above is a fixed, hand-curated list, not an exhaustive model
of every way a fabrication could be worded, and a real weakness of any
closed-vocabulary or blacklist check is that it will not catch a
fabrication built entirely from already-permitted words.

**The stricter gate visibly changed real model behavior, not just its
theoretical bound.** Model-authored rewrites dropped from 20/165
(12.1%) under the previous, weaker gate to 12/165 (7.3%) here — the
same real local model, run against the same real data, producing
fewer accepted rewrites once the gate stopped accepting anything that
merely avoided an unfamiliar capitalized word. This is the practical
effect of preferring the safer design: in the large majority of real
cases (92.7%), the deterministic template is what gets shown, not a
model paraphrase.

**Only 9 distinct explanation strings appeared across 165 attempted
explanations, a disclosed limitation**: since the fallback template is
built from category and content-similarity flags alone, users who
share a dominant category receive an identical sentence. Explanations
here are grounded and checked, but personalized only to the same
coarse category level the ranking model itself uses for
`category_match` — not to any finer-grained signal. A model
contribution rate this low means most of that repetition isn't broken
up by genuine model-authored variation either.


## What this metric is, and what it is not

The number above is a **lexical-policy pass rate**: the share of
produced explanations containing no vocabulary outside the approved
template plus a small set of grammatical connectives. It was previously
called a "faithfulness rate", which overstated it.

A lexical check cannot establish semantic faithfulness. Approved words
can be reordered into a different claim, a subject and object can be
swapped, and an unsupported assertion can be constructed entirely from
permitted vocabulary. Those are not hypothetical:
`tests/test_explanation_generation.py` contains four such sentences and
asserts that the gate passes each one.

That limitation is why the factual relationship is no longer produced
by a model at all. Facts are extracted into a structured value, one of
three approved templates is selected by which evidence is present, and
only a validated category is substituted. Generative rewriting remains
available behind an explicit opt-in, where the lexical gate is a
backstop rather than a guarantee.
