# Ranking Features

Phase 4's ranking model scores a candidate set, not the whole catalog —
that asymmetry with retrieval (`docs/retrieval-model.md`) is exactly why it
can afford richer, more expensive-per-item features than the two-tower
model's category/subcategory pair. Implementation:
`src/recommender/ranking/features.py`.

## A deliberate departure from ranking retrieval's own candidates

The ranking model here is evaluated against the same frozen candidate-set
definition Phase 2's baselines used (`docs/evaluation-protocol.md`) — MIND's
own impression list, K=10 — rather than against Phase 3's own top-N
retrieval output. This is a disclosed methodological choice, not an
oversight: `docs/retrieval-evaluation.md` already found and explained a
severe, specific limitation in the current retrieval implementation (the
item tower's category/subcategory-only features collapse the catalog into
284 distinct vectors). Ranking those same candidates would only re-surface
an already-diagnosed problem, not answer anything new. Isolating "does a
dedicated ranking model improve quality" from "is the current retrieval
implementation's candidate generation good enough" keeps those two
questions — RQ1 (already answered) and RQ2 (this phase's question) —
independently testable. The two-tower model still contributes: its
retrieval score is one input feature to the ranker below, not the
candidate-generation mechanism.

**Update (`docs/deployment-representative-evaluation.md`)**: this
disclosed choice means the frozen-candidate-list numbers alone don't
say what a real user of the deployed system actually receives. A
separate, real end-to-end evaluation now exists that calls the actual
`/recommend` pipeline (retrieval, ranking, and reranking together) and
is reported alongside — not in place of — the numbers here.

## The six features

Computed per (impression, candidate) pair, one row per candidate the
ranker will score:

| Feature | What it measures |
|---|---|
| `retrieval_score` | Two-tower dot product for this (user, candidate) pair — the learned embedding-compatibility signal from Phase 3, carried forward as one input among several. |
| `popularity` | The popularity baseline's training click count (`docs/baselines.md`) for the candidate, log-transformed. |
| `category_match` | 1 if the candidate's category matches the user's single most common history category, else 0. |
| `content_similarity` | Cosine similarity between the candidate's TF-IDF vector and the mean TF-IDF vector of the user's history — reuses the content-similarity baseline's vectorizer (`docs/baselines.md`). |
| `user_history_length` | Count of real (non-padding) history items for this user — an honest cold-start proxy. |
| `hour_of_day` | Hour (0–23) extracted from this impression's own timestamp. |

Article freshness (named in the phase description) is not included:
`news.tsv`'s schema (`src/recommender/data/schema.py`) has no publish-date
field at all. Recorded as a real data limitation rather than approximated
with a substitute that would look like a genuine signal and isn't one.

## No feature can see the future

Every history-derived feature (`category_match`, `content_similarity`,
`user_history_length`) is computed only from a user's `history` field,
which MIND itself defines as everything before this impression — nothing
new enforced here, just confirmed. `hour_of_day` comes from the current
impression's own `time` value, never a later one. `retrieval_score` and
`popularity` come from a model and click counts fit only on `train`.
`build_feature_context` fits popularity, TF-IDF, and catalog embeddings
once per split (train), reused across every row, so train and validation
feature-building never accidentally use different fitted state.

Verified with targeted tests (`tests/test_ranking_features.py`), including
one that deliberately gives two impressions opposite-category histories
and matching candidates — a wrong impression-to-history mapping would flip
one of the two `category_match` results, not just look slightly off.
