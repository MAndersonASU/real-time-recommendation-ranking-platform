# Faiss Candidate Index

Item embeddings from the trained two-tower model
(`docs/retrieval-model.md`), indexed for search rather than compared one
at a time. Implementation: `src/recommender/retrieval/index.py`,
`build_index.py`.

## What was built

- **Exact index** (`IndexFlatIP`): brute-force inner-product search over
  all 51,282 catalog embeddings — the ground truth every approximate
  result gets checked against.
- **Approximate index** (`IndexIVFFlat`, inner-product metric, 256
  clusters): k-means-clustered at build time; at query time, only the
  `nprobe` nearest clusters to the query get searched.

## Real result: recall against exact search, by `nprobe`

500 validation-derived user query vectors, top-50 candidates, measured
against the exact index's own top-50 for the same queries.

| `nprobe` | Recall@50 vs. exact | Seconds/query |
|---|---|---|
| 1 (of 256 clusters) | 0.211 | 0.0000041 |
| 8 | 0.624 | 0.0000050 |
| 32 | 0.891 | 0.0000147 |
| 256 (every cluster) | 0.904 | 0.0000616 |
| exact search | 1.000 (by definition) | 0.0000631 |

The speed/accuracy tradeoff the index exists to manage is clearly
present: recall climbs steadily from probing 1 cluster to 32, and
searching every cluster (`nprobe = nlist`) approaches — but does not
quite reach — the same latency as exact search, which is the expected
behavior of an index degenerating toward brute force as `nprobe` grows.

## A real limitation this exposed, not a bug in the index

`nprobe = 256` (every cluster probed) should, in principle, match exact
search exactly — and it doesn't: recall caps at 0.904, not 1.0. Checked
directly rather than assumed to be a tuning issue: the 51,282 catalog
items produce only **284 distinct embedding vectors**. The current item
tower (`docs/retrieval-model.md`) encodes each item purely from category
and subcategory, and there are only 283 distinct category/subcategory
pairs in the catalog — every article sharing a category and subcategory
gets an identical vector, roughly 180 items per distinct vector on
average.

With that many items tied at the exact same score, "the correct top-50"
isn't a uniquely defined answer to begin with — exact and approximate
search can legitimately return different subsets of a large tied group
without either being wrong. This isn't an index bug; it's a direct,
structural consequence of a real limitation in the item tower's current
feature set. The model, as built in the item tower's current design
(`docs/retrieval-model.md`), cannot yet
distinguish between two different articles in the same category — a
concrete, quantified argument for enriching the item tower with
per-article features (e.g., title-derived text signal) in future work,
left as a documented limitation rather than reopened here, since
revisiting that architecture is a materially larger change than
this step's scope.

## Regression coverage

`tests/test_index.py` verifies the property that motivated this
investigation directly, on synthetic data with genuinely unique vectors
(no ties by construction): when `nprobe` equals the number of clusters,
recall against exact search is exactly 1.0, not merely close — confirming
the real catalog's sub-1.0 ceiling is explained by tied vectors, not by
an implementation error.

Indexes saved to `data/processed/mind_small/faiss_exact.index` and
`faiss_ivf.index` (gitignored, reproducible via
`python -m recommender.retrieval.build_index`).
