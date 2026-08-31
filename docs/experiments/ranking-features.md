# Ranking features

The ranker scores a small candidate list, not the full catalog. It can
therefore use several per-candidate signals after retrieval.

Implementation: `src/recommender/ranking/features.py`.

## Evaluation boundary

The component-level ranking evaluation uses MIND's supplied impression
candidates and K=10, matching the
[frozen baseline protocol](evaluation-protocol.md). This isolates the
question “does the ranker order a given candidate list well?”

The two-tower score still enters the ranker as a feature, but the
two-tower model does not generate the candidate list in this
component-level evaluation.

The [serving-path evaluation](serving-path-end-to-end-evaluation.md)
answers the broader question by running retrieval, ranking, and
reranking together. Results from the two protocols should be shown
together but not combined.

## Feature table

Six features are computed and persisted; the trained model actually uses five of them.
`popularity` remains in the table for comparison but is
excluded from model input based on the
[ranking model ablation](ranking-model.md).

| Feature | Used by the model? | What it measures |
|---|---|---|
| `retrieval_score` | Yes | Two-tower dot product for the user and candidate |
| `popularity` | No — computed, excluded | Log-transformed training click count |
| `category_match` | Yes | Whether the candidate matches the user's most common history category |
| `content_similarity` | Yes | Cosine similarity between the candidate and mean user-history TF-IDF vectors |
| `user_history_length` | Yes | Number of real, non-padding history items |
| `hour_of_day` | Yes | Hour from the current impression timestamp |

The dataset has no article publication timestamp, so the ranker cannot
compute true article freshness. The project does not substitute another
field and label it as freshness.

## Time-safety rules

- `category_match`, `content_similarity`, and
  `user_history_length` use only the history supplied before the current
  impression.
- `hour_of_day` comes from the current impression.
- `retrieval_score` uses a model fitted on training data.
- `popularity` uses training click counts.
- `build_feature_context` fits popularity, TF-IDF, and catalog
  embeddings on `train`, then reuses that context for validation.

`tests/test_ranking_features.py` checks these rules. One test uses two
impressions with opposite category histories, so an incorrect
impression-to-history join produces a clear failure.
