# Full-catalog retrieval evaluation

Source: [`reports/retrieval-evaluation.json`](../../reports/retrieval-evaluation.json).

This evaluation asks whether the clicked article appears among 100
candidates retrieved from the full 51,282-item catalog.

It is not the same task as the baseline evaluation:

| Evaluation | Candidate source | Output size |
|---|---|---|
| Baselines | About 37 candidates already supplied by MIND | K = 10 |
| Retrieval | Full 51,282-item catalog through exact Faiss search | N = 100 |

The values are therefore not directly comparable. Exact search is used
to measure model quality without approximate-index error.

Implementation:
`src/recommender/evaluation/evaluate_retrieval.py`.

## Result

The run covers all 30,270 validation impressions. “Before” is the
category-and-subcategory-only item tower. “After” adds a content vector
from each article's title and abstract.

| Metric | Before | After | Change |
|---|---|---|---|
| Hit rate@100 | 0.0044 | **0.0336** | 7.6x |
| Recall@100 | 0.0026 | **0.0229** | 8.8x |
| NDCG@100 | 0.0006 | **0.0060** | 10x |
| MRR | 0.0002 | **0.0027** | 13.5x |
| Catalog coverage@100 | 0.2194 | **0.3313** | 1.5x |
| Distinct items recommended | — | 16,990 | — |

Distinct catalog vectors increased from 284 to 50,704 across 51,282
articles. The model can now distinguish almost every article instead of
mostly distinguishing category pairs.

## Read the result carefully

The correction produced large relative gains but low absolute quality.
A hit rate@100 of 0.0336 means the clicked article is absent from the
100 retrieved candidates about 96.6% of the time.

Randomly choosing 100 of 51,282 articles would hit about 0.195% of the
time. The current 3.36% is about 17 times that chance rate; the older
0.44% was about 2.25 times chance.

Coverage moved by 1.5×, not by the 7.6–13.5× range observed for the four
relevance measures.

## What caused the older result

The former item tower encoded only category and subcategory. Those two
fields produced 284 distinct vectors, so roughly 180 articles shared a
vector on average. Faiss could identify a topic but had little basis for
choosing one article from a large tied group.

The current tower adds deterministic TF-IDF and SVD features from title
and abstract. The features are content-based rather than article-ID
embeddings, so an article without training clicks can still receive a
vector.

The vector collapse is measurably gone. This evaluation does not isolate
the cause of the remaining quality ceiling, so the documentation does
not assign one.

## Answer to RQ1

- Per-article content features removed the category-level vector
  collapse.
- Hit rate, Recall, NDCG, and MRR improved by 7.6–13.5×.
- Catalog coverage improved by 1.5×.
- Absolute full-catalog retrieval quality remains low.
- These are post-selection development results, not a final
  generalization estimate.

See the [frozen evaluation protocol](evaluation-protocol.md),
[retrieval model](retrieval-model.md), and
[archived index investigation](../archive/faiss-index.md).
