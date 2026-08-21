# Freshness Reranking

RQ3 explicitly names freshness alongside diversity
(`docs/research-scenario.md`), so this control is in scope — but the
guide's own caveat for this step is to use time-aware boosts "only when
supported by the research objective," and the harder question came first:
does this dataset actually contain what a freshness signal needs?
Implementation: `src/recommender/reranking/freshness.py`.

## The real limitation, confirmed again

`news.tsv` has no publish-date field at all — already found when article
freshness was considered as a ranking feature (`docs/ranking-features.md`).
That still holds here: true publication age isn't recoverable from this
dataset, for any reranking policy. What the data does have is weaker but
real — every impression carries its own timestamp, and lists which
candidates it showed. That's enough to compute the earliest moment any
item is ever observed as a candidate in `train` — not when it was
published, a recency proxy built from observation history, labeled as
exactly that rather than presented as true freshness.

## Measured before choosing a threshold

- **53.9%** of distinct validation candidates were never observed as a
  candidate in `train` at all — treated as age 0 (maximally fresh), not a
  missing value, since "never seen before" is the strongest freshness
  signal this proxy can express.
- At a **12-hour** age threshold, **36.3%** of all validation candidate
  rows count as fresh, and only **0.7%** of impressions have zero
  candidates that clear it — common enough that a quota is almost always
  satisfiable, scarce enough to mean something.

## The policy: a quota, not a soft score boost

`apply_freshness_quota` runs after the diversity-constrained slate
(`docs/reranking-diversity.md`):

1. If the slate already has at least 2 items at or under the 12-hour
   threshold, it's left unchanged.
2. Otherwise, the best-scored fresh candidates not already in the slate
   are swapped in, replacing the slate's weakest (lowest-scored) non-fresh
   items first — giving up relevance from the least valuable positions.

A quota, deliberately, rather than adding a freshness term to the score
and re-sorting: a quota guarantees an exact, known number of fresh items
in the final slate, directly stated and verified; a soft boost only
changes the result indirectly, through however it interacts with every
other score component. One disclosed simplification: the swap-in step
does not re-check the diversity policy's category cap, so this runs as its own
separate, independently testable pass rather than a single combined rule.

Verified with 5 targeted tests (`tests/test_freshness.py`): the recency
proxy computes the correct earliest-observed time and correctly treats an
unobserved item as age zero; the quota leaves an already-fresh-enough
slate untouched; it swaps in the best-scored fresh alternative in place of
the weakest non-fresh slate item when needed; and it leaves the slate
unchanged, rather than forcing something that doesn't exist, when no fresh
alternative is available among the candidates at all.
