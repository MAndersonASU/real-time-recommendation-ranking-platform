# Retrieval Evaluation

The two-tower model plus exact Faiss search, run against the same frozen
`validation` split as all three Phase 2 baselines
(`docs/evaluation-protocol.md`) — but a genuinely different task: searching
the full 51,282-item catalog rather than ranking a roughly 37-item
pre-filtered candidate list. Evaluated at N=100 (the retrieval-stage
candidate count, distinct from K=10 per `docs/research-scenario.md`), not
at K=10 — these numbers are not directly comparable to the baseline table
without accounting for that difference. Exact search deliberately, not the
approximate index, to isolate model quality from the index's already-
measured approximation cost (`docs/faiss-index.md`). Implementation:
`src/recommender/evaluation/evaluate_retrieval.py`.

## Real result

30,270 validation impressions, N=100.

| Metric | Value |
|---|---|
| Hit rate@100 | 0.0044 |
| Recall@100 | 0.0026 |
| NDCG@100 | 0.0006 |
| MRR | 0.0002 |
| Catalog coverage@100 | 0.2194 |

These numbers are weak on every ranking metric — worth stating plainly
rather than hedging. Hit rate is about 2.25x pure random chance (a random
top-100 out of 51,282 items would hit a single-click impression's real
click about 0.195% of the time; the model achieves 0.439%) — a small,
real signal above guessing, not evidence of a working retriever.

## Why, traced through evidence already on record

This result is not a mystery — it follows directly from a limitation
already found and documented in `docs/faiss-index.md`: the item tower
(Step 3.2's design) encodes every catalog item purely from category and
subcategory, collapsing 51,282 items into only 284 distinct embedding
vectors. In practice, that means the model's retrieval decision is
functionally a *category-level* guess, not an item-level one — at best it
can identify which of 283 category/subcategory clusters a user's next
click probably falls into, but has zero signal to distinguish between the
roughly 180 different articles that share every one of those clusters'
identical vectors. Even a correct category-level guess still has to
arbitrarily select 100 of however many tied items exist in that cluster,
and the genuinely correct article is one specific item among that tied
group — explaining both the very low hit rate (the right category, wrong
specific article, most of the time) and the comparatively higher catalog
coverage (0.2194 — many different tied clusters get queried across 30,270
different users, so a wide swath of the catalog appears *somewhere*
across all recommendations, even though any single recommendation is
usually wrong).

This chains three separate, independently-verified findings into one
coherent explanation rather than three unrelated observations: Step 2.4
found SVD's item factors only existed for 29.2% of validation candidates
(a data-sparsity limitation); Step 3.4 found the item tower's features
collapse the catalog into 284 distinct vectors (an architecture
limitation); this step shows that architecture limitation is severe
enough to suppress real item-level retrieval almost entirely. The fix is
already named and scoped in `docs/faiss-index.md`: enrich the item tower
with per-article features (e.g., title-derived text signal), not
something reopened here, since that's a materially larger change than
this step's evaluation scope.

## Honest answer to RQ1

RQ1 asks how much learned embeddings and candidate retrieval improve
recommendation quality over simple baselines. The honest answer from this
implementation is: **not demonstrated, and for a specific, diagnosed
reason** — not because learned embeddings are inherently weaker than the
Phase 2 baselines, but because this particular item tower's feature set
is too coarse to support item-level retrieval at all. That is a real,
falsifiable finding about *this* architecture, not a verdict on learned
embeddings in general, and it points directly at what a follow-up
architecture would need to fix to give RQ1 a fair test.
