# Evaluating Explanations Separately

Recommendation quality (hit rate, recall, NDCG, MRR) measures whether
the right item appeared in a slate. None of those numbers say anything
about whether an explanation attached to that item is honest or
useful — a different property, measured here with its own metrics,
never folded into the ranking numbers tracked since the baselines.
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
 this evaluation shared the serving-path gate's exact design and
  therefore its exact blind spot (`docs/experiments/explanation-boundary.md`).
- **Model-contribution rate** — of the explanations shown, how many
  are the local model's own rewrite versus the safe fallback template,
  the honest measure of how much the generative layer itself actually
  contributes.

## Result, 60 real validation users, 180 real recommendations

Measured after the lexical policy gate was rebuilt as a closed-vocabulary
check (`docs/experiments/explanation-boundary.md`) — the model's rewrite must now
consist only of words already in the template plus a small, fixed set
of grammatical connectives, not just avoid unfamiliar capitalized words.
Users are a seeded uniform sample of the validation split's distinct
users (`recommender.evaluation.sampling`), not the first 60 to appear;
an earlier version of this evaluation took the first 60, which is why
this sample's exact counts differ from a previous version of this page
even though the users evaluated and the totals they produce are drawn
from the same 180-recommendation shape (60 users x 3 candidates).

| Metric | Value |
|---|---|
| Total recommendations evaluated | 180 |
| Refused (no supporting evidence) | 37 (20.6%) |
| Attempted explanations | 143 |
| Lexical-policy pass rate | 100% (143/143) |
| Model rewrite used | 0 (0.0% of attempted) |
| Template fallback used | 143 (100.0% of attempted) |
| Mean explanation length | 96.5 characters |
| Distinct explanation strings | 11 |

Generated from [`reports/explanation-evaluation.json`](../../reports/explanation-evaluation.json).

## Interpretation and limitations

No violations were detected in this evaluated sample under the
documented checks — all 143 attempted explanations passed both the
serving-path gate and the separate, differently-designed verification. That is a statement about this sample under these
checks, not a claim that no rewrite could ever slip through: the
blacklist above is a fixed, hand-curated list, not an exhaustive model
of every way a fabrication could be worded. A known weakness of any
closed-vocabulary or blacklist check is that it will not catch a
fabrication built entirely from already-permitted words.

**The stricter gate changed measured model behaviour, not just its
theoretical bound.** In the default configuration the generative
rewriting path is off, so model-authored rewrites are 0 of 143
attempted and the deterministic template supplies every shown
explanation (143/143). Under the earlier, weaker gate the same local
model produced accepted rewrites; the closed-vocabulary gate stopped
accepting wording that merely avoided an unfamiliar capitalized word.

**The refusal rate and explanation diversity moved substantially since
the previous measurement (66.1% refused / 2 distinct strings ->
20.6% refused / 11 distinct strings), and the reason is known, not a
sampling artifact:** this rerun follows SERVING-DURABLE-HISTORY-69's
fix to the serving path's retrieval history selection. The explanation
gate's supporting evidence (`category_match`, `content_similarity`,
`retrieval_score` in `MatchedSignals`) is far more often genuinely
present now that a returning user with durable history but no live
Redis record is retrieved for on their own history rather than the
same unpersonalized global-popularity pool every such user used to
share -- exactly the retrieval-personalization gap that fix closed. The
same 60-user seeded sample was used both times; the swing is
attributable to the retrieval-path fix, not a different draw.

**11 distinct explanation strings appeared across 143 attempted
explanations, still a disclosed limitation**: since the fallback
template is built from category and content-similarity flags alone,
users who share a dominant category and a similar content-similarity
band still receive an identical sentence. Explanations here are
grounded and checked, but personalized only to the same coarse
category/similarity level the ranking model itself uses for
`category_match`/`content_similarity` — not to any finer-grained
signal. A model contribution rate this low means most of that
repetition isn't broken up by genuine model-authored variation either.


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
