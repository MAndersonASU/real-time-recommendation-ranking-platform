# Retrieval Evaluation

The two-tower model plus exact Faiss search, run against the same frozen
`validation` split as all three baselines
(`docs/experiments/evaluation-protocol.md`) — but a genuinely different
task: searching the full 51,282-item catalog rather than ranking a
roughly 37-item pre-filtered candidate list. Evaluated at N=100 (the
retrieval-stage candidate count, distinct from K=10 per
`docs/research-scenario.md`), not at K=10 — these numbers are not
directly comparable to the baseline table without accounting for that
difference. Exact search deliberately, not the approximate index, to
isolate model quality from the index's already-measured approximation
cost (`docs/archive/faiss-index.md`). Implementation:
`src/recommender/evaluation/evaluate_retrieval.py`.

## Results

30,270 validation impressions, N=100. The "before" column is the
category/subcategory-only item tower this project originally shipped;
"after" is the same evaluation once the item tower gained per-article
content features (`docs/experiments/retrieval-model.md`).

| Metric | Before | After | Change |
|---|---|---|---|
| Hit rate@100 | 0.0044 | **0.0336** | 7.6x |
| Recall@100 | 0.0026 | **0.0229** | 8.8x |
| NDCG@100 | 0.0006 | **0.0060** | 10x |
| MRR | 0.0002 | **0.0027** | 13.5x |
| Catalog coverage@100 | 0.2194 | **0.3313** | 1.5x |
| Distinct items recommended | — | 16,990 | — |

The architecture limitation that produced the "before" column is gone:
the item tower now emits **50,704 distinct embedding vectors** across
51,282 catalog items, against 284 before. Retrieval is making an
item-level decision rather than a category-level one for the first time.

These numbers are still low in absolute terms, and that is worth stating
plainly rather than dressing up: hit rate@100 of 3.4% means the user's
actual next click is absent from a 100-item candidate set from a
51,282-item catalog about 97% of the time. It is roughly 17x random
chance (a random top-100 would hit about 0.195%) where the previous
model managed 2.25x. Real, large, and still not a solved retrieval
problem.

## Why the original result happened, and what changed

The original result was not a mystery — it followed directly from a
limitation documented in `docs/archive/faiss-index.md`: the item tower encoded
every catalog item purely from category and subcategory, collapsing
51,282 items into 284 distinct embedding vectors. Retrieval was
functionally a *category-level* guess. At best it identified which
cluster a user's next click fell into, with no signal at all to
distinguish the roughly 180 articles sharing each cluster's identical
vector, and it then had to arbitrarily select 100 of however many tied
items existed there.

That chained three independently-verified findings into one explanation:
the baseline evaluation (`docs/experiments/baselines.md`) found SVD item factors
existed for only 29.2% of validation candidates (data sparsity); the
index investigation (`docs/archive/faiss-index.md`) found the 284-vector
collapse (architecture); this evaluation showed the architecture
limitation was severe enough to suppress item-level retrieval almost
entirely.

**The named fix has now been made.** `docs/archive/faiss-index.md` scoped it as
"enrich the item tower with per-article features (e.g., title-derived
text signal)", and that is exactly what changed: each article now
carries a dense content vector reduced from the TF-IDF of its own title
and abstract, alongside the existing category and subcategory
embeddings (`build_item_content_matrix` in
`src/recommender/retrieval/features.py`). The vector is content-derived
rather than id-derived, so an article never seen in training still gets
a real embedding and the item tower keeps working for cold items.

The measured effect is the "after" column above. The remaining gap is no
longer explained by the embedding collapse, which is fixed; what limits
the result now is the modest capacity of a 32-dimensional two-tower
model trained on the five-day `train` split (2019-11-09 to 2019-11-13,
`docs/experiments/splits.md`), which is a different and smaller claim
than the original diagnosis.

## Interpretation: RQ1

RQ1 asks how much learned embeddings and candidate retrieval improve
recommendation quality over simple baselines. Four statements hold
together:

1. **The original collapse was fixed.** The item tower once embedded only
 category and subcategory, producing 284 distinct catalog embeddings
 across the 51,282-item catalog. Per-article content vectors removed
 that degeneracy: there are now 50,704 distinct embeddings across
 those same 51,282 items.
2. **Retrieval improved substantially.** Hit rate@N rose from 0.0044 to
 0.0336, a 7.6x improvement, with comparable gains across the other
 retrieval metrics.
3. **Absolute retrieval quality remains low.** Hit rate@N is 0.0336,
 Recall@N 0.0229 and NDCG@N 0.0060. Retrieval alone does not yet beat
 the baselines on this dataset.
4. **The remaining gap is not the old defect.** Whatever explains the
 current ceiling, it is not the 284-vector collapse, which is measurably
 gone. Naming a cause would require an experiment this project has not
 run.

These are post-selection development results under the candidate-list
protocol, not a final generalization estimate; no untouched evaluation
split remains. See
[`docs/experiments/evaluation-protocol.md`](evaluation-protocol.md) for
what that protocol does and does not support.
