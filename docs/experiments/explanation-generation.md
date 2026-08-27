# Generating Bounded Explanations

A local, instruction-tuned model (`google/flan-t5-small`, 77M
parameters, Apache 2.0, no external API) turns retrieved support
context into a short "why recommended" sentence. What the current
implementation actually does was shaped directly by measured model
behavior, not by the first design that seemed reasonable. Generative
rewriting is opt-in and disabled by default
(`allow_generative_rewrite`) -- an ordinary request gets the
deterministic template. Implementation:
`src/recommender/explanation/generation.py`.

## The real refusal rule

`has_sufficient_evidence` refuses outright, with no model call at all,
unless at least one of two signals supports the recommendation:
the item's category matching the user's own dominant history category,
or a real, non-negligible content-similarity score. A recommendation
resting entirely on the learned retrieval score alone — already
diagnosed as weak on its own (`docs/conclusions.md`, RQ1) — has no
real, human-checkable evidence an explanation could honestly cite.

## Three real attempts, in order, and what each one produced

**Attempt 1 — free generation from the article's own title and
abstract.** Real output on real recommended items included at least
one outright factual corruption: given the real title *"I'm Afraid to
Tell My Male Bosses I'm Pregnant,"* the model produced *"I'm afraid to
tell my male boyfriends I'm pregnant"* — a fabricated word substitution,
not a paraphrase. Other outputs were merely redundant restatements of
the title rather than an explanation of why it was recommended.
Rejected: an explanation layer that can invent a fact defeats the
purpose of the whole component.

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
(`build_template_explanation`) — built directly and only from the real
matched signals, with no free-text generation involved at all — as the
one part of this feature whose correctness is enforced by construction,
not by a check that could itself have a gap. The model is asked only
to reword that exact sentence, and its rewrite is used only if it
passes `_preserves_required_facts`: the real category name is still
present (when a category match is the evidence), and every other word
in the rewrite is either already in the template or a small, fixed set
of grammatical connectives — a stricter check than an earlier version
of this gate used, which only flagged unfamiliar *capitalized* words; a
follow-up review found real, reproduced fabrications that check missed
entirely, since a fabricated claim does not have to be capitalized to
be one (`docs/experiments/explanation-evaluation.md` has the current Results).
If
the rewrite fails, the response falls back to the unmodified template.
That fallback is unconditional and factually correct by construction;
the gate that decides whether to use the rewrite instead is a real,
tested check against a documented set of failure modes, not a proof
that no fabrication could ever pass it.

## Superseded: a 15-recommendation, 5-user pilot

The table below was the first measurement taken with this design, before
`docs/experiments/explanation-evaluation.md`'s frozen protocol and its
machine-readable report existed. It is kept for the qualitative pattern
it shows, not as a current result -- **current numbers are the 180-request
sample in `docs/experiments/explanation-evaluation.md`**
([`reports/explanation-evaluation.json`](../../reports/explanation-evaluation.json)),
where the model's rewrite is kept 0 times out of 65 attempts, not 2 of 14.

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
consistent with attempt 3's finding above.

The larger, current sample found the rewrite trustworthy even less
often -- zero times, not two. **This is reported plainly as a
limitation of this small local model at this task, not smoothed over**:
its verified contribution is, at best, an occasional wording variation
on top of a deterministic sentence that does the actual explanatory
work, never a fully generative capability, and the current sample did
not observe even that.
