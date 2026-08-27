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

## Results: recall against exact search, by `nprobe`

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

## A limitation this exposed, not a bug in the index

`nprobe = 256` (every cluster probed) should, in principle, match exact
search exactly — and it doesn't: recall caps at 0.904, not 1.0. Checked
directly rather than assumed to be a tuning issue: at the time of this
measurement the 51,282 catalog items produced only **284 distinct
embedding vectors**. The item tower then encoded each item purely from
category and subcategory, and there are only 283 distinct
category/subcategory pairs in the catalog — every article sharing a
category and subcategory got an identical vector, roughly 180 items per
distinct vector on average.

> **Historical result (superseded).** The measurement above dates from the category/subcategory-only item tower. That limitation was subsequently fixed by giving each article a content vector from its own title and abstract: distinct catalog embeddings rose from 284 to 50,704 and retrieval metrics improved 7.6x-13.5x. See `docs/retrieval-evaluation.md` for the current numbers and `docs/retrieval-model.md` for the change. The original figures are kept here rather than rewritten, so the record of what was measured when stays intact.


With that many items tied at the exact same score, "the correct top-50"
isn't a uniquely defined answer to begin with — exact and approximate
search can legitimately return different subsets of a large tied group
without either being wrong. This was not an index bug; it was a direct,
structural consequence of the item tower's feature set at the time, which
embedded only category and subcategory and so could not distinguish two
articles sharing a category.

That limitation has since been fixed. Each article now carries a content
vector derived from its own title and abstract, and the tied-vector
condition described above no longer holds. Current retrieval numbers are
in [`docs/retrieval-evaluation.md`](retrieval-evaluation.md); the change
itself is described in
[`docs/retrieval-model.md`](retrieval-model.md).

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
