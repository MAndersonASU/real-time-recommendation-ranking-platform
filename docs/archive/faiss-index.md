# Archived Faiss index measurement

> **Historical record.** This measurement used the former
> category-and-subcategory-only item tower. The current model also uses
> title and abstract content. See the
> [current retrieval evaluation](../experiments/retrieval-evaluation.md).

The experiment compared two Faiss indexes over 51,282 catalog
embeddings:

| Index | Search behavior |
|---|---|
| `IndexFlatIP` | Exact inner-product search over the full catalog |
| `IndexIVFFlat` | Approximate search over 256 clusters, examining only the configured `nprobe` clusters |

Implementation: `src/recommender/retrieval/index.py` and
`src/recommender/retrieval/build_index.py`.

## Historical result

The run used 500 validation-derived user vectors and requested 50
candidates. Recall compares each approximate result with the exact
index's top 50 for the same query.

| `nprobe` | Recall@50 vs. exact | Seconds/query |
|---|---|---|
| 1 (of 256 clusters) | 0.211 | 0.0000041 |
| 8 | 0.624 | 0.0000050 |
| 32 | 0.891 | 0.0000147 |
| 256 (every cluster) | 0.904 | 0.0000616 |
| exact search | 1.000 (by definition) | 0.0000631 |

More clusters improved recall and increased query time. Probing all 256
clusters approached exact-search latency but reached only 0.904 recall.

## Why full probing did not reach 1.0

The result came from tied item vectors, not an index defect. The old
item tower encoded only category and subcategory. It produced 284
distinct vectors for 51,282 articles, so many items received identical
scores. Exact and approximate search could return different valid
subsets from a large tied group.

The current content-aware item tower increased distinct vectors from
284 to 50,704. Under its evaluation, the four relevance measures
improved by 7.6–13.5× and catalog coverage improved by 1.5×. See the
[retrieval model](../experiments/retrieval-model.md) and
[retrieval evaluation](../experiments/retrieval-evaluation.md).

## Regression coverage

`tests/test_index.py` uses unique synthetic vectors. When `nprobe`
equals the number of clusters, approximate recall is exactly 1.0. This
isolates the historical shortfall to tied catalog vectors.

Generated indexes are ignored by Git:

- `data/processed/mind_small/faiss_exact.index`
- `data/processed/mind_small/faiss_ivf.index`

Rebuild them with:

```bash
python -m recommender.retrieval.build_index
```
