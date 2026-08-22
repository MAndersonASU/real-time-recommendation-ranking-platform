# Generating Bounded Explanations

A local, instruction-tuned model (`google/flan-t5-small`, 77M
parameters, Apache 2.0, no external API) turns retrieved support
context into a short "why recommended" sentence. What actually reached
production here was shaped directly by real, measured model behavior,
not by the first design that seemed reasonable. Implementation:
`src/recommender/explanation/generation.py`.

## The real refusal rule

`has_sufficient_evidence` refuses outright, with no model call at all,
unless at least one of two real signals supports the recommendation:
the item's category matching the user's own dominant history category,
or a real, non-negligible content-similarity score. A recommendation
resting entirely on the learned retrieval score alone — already
diagnosed as weak on its own (`docs/conclusions.md`, RQ1) — has no
real, human-checkable evidence an explanation could honestly cite.

## Three real attempts, in order, and what each one actually produced

**Attempt 1 — free generation from the article's own title and
abstract.** Real output on real recommended items included at least
one outright factual corruption: given the real title *"I'm Afraid to
Tell My Male Bosses I'm Pregnant,"* the model produced *"I'm afraid to
tell my male boyfriends I'm pregnant"* — a fabricated word substitution,
not a paraphrase. Other outputs were merely redundant restatements of
the title rather than an explanation of why it was recommended.
Rejected: an explanation layer that can invent a fact defeats the
purpose of the whole phase.

**Attempt 2 — a fill-in-the-blank prompt that withheld the article's
title entirely**, so there was nothing article-specific left to
hallucinate. This eliminated fabricated facts, but the model's
completions were generic and uninformative regardless of the real
category given ("The user is a reader," "The article is a good source
for reading comprehension") — safe, but useless.

**Attempt 3 — asking the model to paraphrase an already-correct,
fully-deterministic template sentence**, changing only its wording.
This also avoided inventing new facts, but reliably *dropped* the one
real fact it was given: `"Recommended because it matches your interest
in lifestyle."` came back as `"It is a good choice for you."` — safe
from fabrication, but no longer actually explanatory.

## The design this evidence led to

Given all three prompting strategies, the model was consistently either
unsafe (attempt 1) or uninformative (attempts 2 and 3) on its own. The
adopted design keeps the deterministic template
(`build_template_explanation`) as the guaranteed-correct source of
truth, asks the model only to reword that exact sentence, and applies
a real, checkable faithfulness gate (`_preserves_required_facts`)
before ever using the model's rewrite: does it still contain the real
category name it was given. If not, the response falls back to the
unmodified template — always factually correct, never blank, never
inventing anything.

## Real result across 15 real recommendations, 5 real users

| Outcome | Count |
|---|---|
| Refused (no supporting evidence) | 1 |
| Fell back to the safe template | 12 |
| Model rewrite kept and used | 2 |

The one correct refusal had neither a category match nor a
content-similarity signal. Of the 14 attempted explanations, the
model's own rewrite was judged trustworthy and used only twice — both
genuine cases where the rewrite happened to retain the real category
word (`"It is a good choice for a tv show."`, category `tv`). The
other 12 dropped the required fact and fell back to the template,
consistent with attempt 3's finding above. **This is reported plainly
as a real limitation of this small local model at this task, not
smoothed over**: its practical, verified contribution here is a
minority-case wording variation on top of a deterministic sentence that
does the actual explanatory work, not a fully generative capability.
