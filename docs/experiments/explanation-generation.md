# Bounded explanation generation

The default explanation is a deterministic sentence built from matched
ranking evidence. Optional rewriting uses local
`google/flan-t5-small`, a 77-million-parameter Apache 2.0 model. No
external API is called.

Generative rewriting is disabled unless
`allow_generative_rewrite=True`.

Implementation:
`src/recommender/explanation/generation.py`.

## Evidence requirement

`has_sufficient_evidence` requires at least one:

- the article category matches the user's dominant history category; or
- content similarity is above the minimum evidence threshold.

Retrieval score alone is not considered a human-checkable reason. When
neither allowed signal exists, the component refuses without calling
the language model.

## Prompt tests

Three prompt designs were tested on real recommendations:

| Design | Observed behavior | Decision |
|---|---|---|
| Generate from title and abstract | Could change a factual word and often repeated the title | Rejected |
| Fill a blank without the title | Avoided article-specific errors but produced generic text | Rejected |
| Reword a correct template | Often removed the supporting fact | Allowed only behind validation and fallback |

One free-generation example changed “male bosses” to “male boyfriends.”
One template rewrite changed “matches your interest in lifestyle” to
“It is a good choice for you,” removing the reason.

## Current design

`build_template_explanation` creates the factual sentence from
structured matched signals. The language model may only reword that
sentence.

`_preserves_required_facts` accepts a rewrite only when:

- the real category remains when category match is the evidence; and
- every other word comes from the template or a small allow-list of
  grammatical connectors.

If validation fails, the original template is returned. The template is
the explanation; rewriting is optional presentation.

The lexical gate is tested against known failure modes, but it is not a
proof of semantic correctness. Keeping rewriting off by default is the
safer operating choice.

## Historical pilot

The first pilot covered 15 recommendations from 5 users:

| Outcome | Count |
|---|---|
| Refused (no supporting evidence) | 1 |
| Fell back to the safe template | 12 |
| Model rewrite kept and used | 2 |

The two retained rewrites kept the real category. The other 12 removed a
required fact and fell back.

This pilot is historical. The current
[explanation evaluation](explanation-evaluation.md) covers 180
requests, produces 143 explanations, and refuses 37. Generative
rewriting is off in that run, so model-authored text is used 0 times.
See the
[machine-readable report](../../reports/explanation-evaluation.json).

The measured contribution of the local model is therefore limited. The
deterministic template performs the actual explanatory work.
