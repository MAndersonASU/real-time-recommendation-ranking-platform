# Baselines

Reproducible results for each baseline defined in Phase 2, evaluated
against the Step 1.5 `validation` split using the frozen metrics from
`docs/research-scenario.md` and `src/recommender/evaluation/metrics.py`.
K=10 throughout. Methodology for each model:
`src/recommender/evaluation/evaluate_baseline.py` (popularity) and its
successors as later baselines are added.

## Popularity baseline

Ranks each impression's candidates by how many times they were clicked in
the `train` split — no personalization, no content signal, the same
ranking policy applied to every user. Implementation:
`src/recommender/ranking/baselines.py`.

| Metric | Value |
|---|---|
| Hit rate@10 | 0.5697 |
| Recall@10 | 0.5034 |
| NDCG@10 | 0.2830 |
| MRR | 0.2484 |
| Catalog coverage@10 | 0.0370 |

Evaluated on all 30,270 validation impressions. 1,896 distinct items were
ever recommended in a top-10, out of a 51,282-item catalog.

**Reading these numbers correctly matters more than the numbers
themselves.** Hit rate and recall look surprisingly strong for a model
with zero personalization — but that's explained by, not in spite of, the
weak class balance already measured in `docs/data-quality.md`: overall CTR
is only ~4%, and a small number of globally popular items already capture
a large share of all clicks (Step 1.4's category analysis showed the same
concentration pattern one level up). A baseline that just always guesses
"popular" will look reasonable exactly because popular items really do get
clicked disproportionately often — that's a property of the data, not
evidence the baseline understands users.

Catalog coverage is the metric that exposes what hit rate and recall
can't: 3.70% is far below the 12.7–39.6% coverage the real, curated MIND
impression logs themselves showed in Step 1.3. That gap is the expected,
measured cost of pure popularity ranking — it repeatedly surfaces the same
narrow slice of the catalog to everyone. Any later model (Phase 3 onward)
that improves hit rate/NDCG/recall by narrowing coverage further, rather
than widening it, hasn't actually solved the problem this baseline
exposes; RQ3's diversity work in Phase 5 exists specifically to address
this trade-off.

Runtime: the evaluation loop (a Python-level `groupby` over 30,270
impressions) took about 41 seconds locally. Left as-is rather than
optimized — Phase 10 is where profiling and performance work belongs, and
optimizing a one-off local evaluation script before it's ever been a
measured bottleneck would be solving a problem that doesn't exist yet.

## Content-similarity baseline

Ranks each impression's candidates by cosine similarity between the
candidate's TF-IDF vector (title + abstract) and a per-user profile vector
— the mean of the TF-IDF vectors for whatever's in that user's click
history. Falls back to the popularity baseline when history is empty or
references nothing in the catalog. Implementation:
`src/recommender/ranking/baselines.py` (`build_content_vectors`,
`rank_by_content_similarity`).

| Metric | Popularity | Content similarity |
|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 |
| Recall@10 | 0.5034 | 0.5743 |
| NDCG@10 | 0.2830 | 0.3526 |
| MRR | 0.2484 | 0.3236 |
| Catalog coverage@10 | 0.0370 | 0.0722 |

Evaluated on the same 30,270 validation impressions. Content similarity
beats popularity on every metric, including catalog coverage — 3,704
distinct items were recommended in a top-10, versus popularity's 1,896,
roughly double, though still well short of the 12.7–39.6% real curated
logs showed in Step 1.3. 772 of the 30,270 impressions (2.5%) had no
usable history and fell back to the popularity ranking, consistent with
the ~2–3% null-history rate already measured in Steps 1.2–1.3.

**This is real, if modest, evidence toward RQ1** — even a non-learned,
purely lexical content signal (word overlap via TF-IDF, nothing trained)
outperforms recommending the same popular items to everyone, on every
metric measured. It does not yet answer RQ1 on its own: RQ1 specifically
asks about *learned embeddings* (Phase 3's two-tower retrieval model), and
TF-IDF word-overlap similarity is a considerably weaker, hand-computed
stand-in for that. What this result does establish is a second, stronger
rung on the same ladder — Phase 3's embedding model now has to beat this
content-similarity baseline, not just the popularity one, to demonstrate
real value from learned representations.
