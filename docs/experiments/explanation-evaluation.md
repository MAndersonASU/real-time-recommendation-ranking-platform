# Explanation evaluation

Source:
[`reports/explanation-evaluation.json`](../../reports/explanation-evaluation.json).

Recommendation metrics measure whether a clicked article appears.
Explanation metrics measure whether the system has enough evidence to
explain a result and whether the shown text stays within its approved
vocabulary.

Implementation:
`src/recommender/evaluation/evaluate_explanations.py`.

## Measures

| Measure | Meaning |
|---|---|
| Refusal rate | Share of requested explanations declined because no approved evidence was available |
| Lexical-policy pass rate | Share of produced explanations containing only approved template vocabulary and grammatical connectors |
| Model-contribution rate | Share of produced explanations whose wording came from the optional local model |

The report calls a produced, non-refused explanation “attempted.” It is
the denominator for the lexical-policy and model-contribution rates.

The evaluation check differs from the serving gate. Serving uses an
allow-list; evaluation also looks for a fixed set of unsupported entity,
actor, cause, guarantee, and personalization terms.

## Result

A seeded uniform sample selects 60 validation users. Three
recommendations per user produce 180 explanation requests.

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

Generative rewriting is off in the reported configuration. Every shown
explanation therefore comes from a deterministic template.

## What 100% means

All 143 produced explanations passed the documented lexical checks. It
does not mean semantic correctness has been proven.

Approved words can still be rearranged into an unsupported statement.
`tests/test_explanation_generation.py` contains examples that pass the
lexical gate despite changing meaning.

For that reason:

- factual relationships come from structured signals;
- only approved templates state those relationships;
- category substitution is validated; and
- optional rewriting remains off by default.

## Why refusal changed

The earlier run refused 66.1% of requests and produced 2 distinct
strings. The current run refuses 20.6% and produces 11 strings.

Both runs use the same seeded 60-user sample. The change follows
`SERVING-DURABLE-HISTORY-69`: returning users without Redis history now
retrieve from their durable history instead of one global-popularity
pool. Category and content evidence are therefore available more often.

## Remaining limits

- Eleven strings across 143 explanations is still coarse
  personalization.
- The templates reflect category and content-similarity signals, not a
  detailed user narrative.
- A fixed blacklist cannot cover every unsupported statement.
- Model contribution is zero in the default configuration.
- This evaluation measures lexical policy, not human usefulness.

The older name “faithfulness rate” was removed because it claimed more
than the check verifies.

See [explanation boundary](explanation-boundary.md),
[generation policy](explanation-generation.md), and
[evidence lookup](explanation-retrieval.md).
