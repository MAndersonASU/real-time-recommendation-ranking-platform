# Baselines

Generated from [`reports/baseline-evaluation.json`](../../reports/baseline-evaluation.json).

Reproducible results for each defined baseline, evaluated
against the frozen `validation` split (`docs/experiments/splits.md`) using the
metrics from `docs/research-scenario.md` and
`src/recommender/evaluation/metrics.py`. K=10 throughout. Methodology for
each model:
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
weak class balance already measured in `docs/experiments/data-quality.md`: overall CTR
is only ~4%, and a small number of globally popular items already capture
a large share of all clicks (the category-level CTR analysis in
`docs/experiments/data-quality.md` showed the same concentration pattern one level
up). A baseline that just always guesses
"popular" will look reasonable exactly because popular items really do get
clicked disproportionately often — that's a property of the data, not
evidence the baseline understands users.

Catalog coverage is the metric that exposes what hit rate and recall
can't: 3.70% is far below the 12.7–39.6% coverage the real, curated MIND
impression logs themselves showed (`docs/experiments/data-quality.md`). That gap is
the expected, measured cost of pure popularity ranking — it repeatedly
surfaces the same
narrow slice of the catalog to everyone. Any later model (the retrieval model onward)
that improves hit rate/NDCG/recall by narrowing coverage further, rather
than widening it, hasn't actually solved the problem this baseline
exposes; RQ3's diversity work in reranking exists specifically to address
this trade-off.

Runtime: the evaluation loop (a Python-level `groupby` over 30,270
impressions) took about 41 seconds locally. Left as-is rather than
optimized — the scale and performance work is where profiling and performance work belongs, and
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
logs showed (`docs/experiments/data-quality.md`). 772 of the 30,270 impressions (2.5%)
had no usable history and fell back to the popularity ranking, consistent
with the ~2–3% null-history rate already measured during ingestion and
profiling.

**This is real, if modest, evidence toward RQ1** — even a non-learned,
purely lexical content signal (word overlap via TF-IDF, nothing trained)
outperforms recommending the same popular items to everyone, on every
metric measured. It does not yet answer RQ1 on its own: RQ1 specifically
asks about *learned embeddings* (the retrieval model's two-tower retrieval model), and
TF-IDF word-overlap similarity is a considerably weaker, hand-computed
stand-in for that. What this result does establish is a second, stronger
rung on the same ladder — the retrieval model's embedding model now has to beat this
content-similarity baseline, not just the popularity one, to demonstrate
value from learned representations.

## Collaborative baseline

Ranks each impression's candidates by predicted affinity — a dot product
between a user's and a candidate's TruncatedSVD latent factors (20
components), fit on the training click matrix. Candidates never clicked
during training score `-inf`, not 0, since a raw dot product isn't bounded
at zero the way TF-IDF cosine similarity was. Falls back to the popularity
baseline for users with no training click history at all. Implementation:
`src/recommender/ranking/baselines.py` (`build_collaborative_factors`,
`rank_by_collaborative_filtering`).

| Metric | Popularity | Content similarity | Collaborative |
|---|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 | 0.5709 |
| Recall@10 | 0.5034 | 0.5743 | 0.5046 |
| NDCG@10 | 0.2830 | 0.3526 | 0.2847 |
| MRR | 0.2484 | 0.3236 | 0.2509 |
| Catalog coverage@10 | 0.0370 | 0.0722 | 0.0389 |

**Collaborative filtering essentially matches popularity — it does not
come close to content similarity — and this was predictable before
running anything, not a surprise discovered after the fact.** Before
writing any ranking code, a direct check of the training click matrix
against the validation split found that only 29.2% of validation
candidate items were ever clicked during training at all, versus 80.2% of
validation *users* having a known factor. News
articles churn fast enough that most of what's a candidate on any given
day simply wasn't old enough to have accumulated click history during the
training window. With roughly 71% of each impression's candidates scoring
`-inf` — no signal at all — this baseline can only meaningfully rank
the minority of candidates it has actual information about, and the rest
fall back to an arbitrary (alphabetical) order among themselves. On
average that's still usually enough real candidates to mostly fill a
top-10, which is why the result isn't catastrophic, just unimpressive.
4,958 of 30,270 impressions (16.4%) used the full popularity fallback for
having no known user at all — close to, though not identical to, the
19.8% estimated from distinct-user overlap, the difference explained by
counting at the impression level rather than the distinct-user level.

**This result was diagnosed, not just observed.** The weak showing traces
directly and specifically to item cold-start, a structural property of
news measured *before* the model was built, not a mysterious shortfall
discovered by comparing numbers after the fact. A hybrid that blends
collaborative and popularity signal per-candidate (rather than falling
back only when a user is entirely unknown) might close some of this gap,
but that's a different, more complex model than "test what pure
collaborative signal alone can do here" — which is what this baseline was
built to measure, honestly, including a result that isn't flattering.

Runtime: all three baselines combined took about 2m51s locally (up from
1m31s for two), still an accepted local-script tradeoff for the same
reasons given for the two baselines above — not optimized, since nothing
here has been profiled as an actual bottleneck yet.
