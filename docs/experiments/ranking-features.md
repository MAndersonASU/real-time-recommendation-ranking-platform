# Ranking Features

the ranking model scores a candidate set, not the whole catalog —
that asymmetry with retrieval (`docs/experiments/retrieval-model.md`) is exactly why it
can afford richer, more expensive-per-item features than the two-tower
model's category/subcategory pair. Implementation:
`src/recommender/ranking/features.py`.

## A deliberate departure from ranking retrieval's own candidates

The ranking model here is evaluated against the same frozen candidate-set
definition the baselines used (`docs/experiments/evaluation-protocol.md`) — MIND's
own impression list, K=10 — rather than against the retrieval model's own top-N
retrieval output. This is a disclosed methodological choice, not an
oversight: `docs/experiments/retrieval-evaluation.md` had already found and explained a
severe, specific limitation in the retrieval implementation as it stood
(the item tower's category/subcategory-only features collapsed the
catalog into 284 distinct vectors; that cause has since been fixed, and
distinct embeddings now number 50,704). Ranking those same candidates would only re-surface
an already-diagnosed problem, not answer anything new. Isolating "does a
dedicated ranking model improve quality" from "is the current retrieval
implementation's candidate generation good enough" keeps those two
questions — RQ1 (already answered) and RQ2 (this component's question) —
independently testable. The two-tower model still contributes: its
retrieval score is one input feature to the ranker below, not the
candidate-generation mechanism.

**Update (`docs/experiments/serving-path-end-to-end-evaluation.md`)**: this
disclosed choice means the frozen-candidate-list numbers alone don't
say what a real user of this serving code path actually receives. A
separate evaluation now exists that calls the actual `/recommend`
pipeline (retrieval, ranking, and reranking together) against real,
chronologically-ordered, point-in-time-correct state, and is reported
alongside — not in place of — the numbers here.

## Computed features

Computed per (impression, candidate) pair, one row per candidate the
ranker will score. Six features are computed and persisted; the trained
model actually uses five of them — `popularity` is computed and kept in
the persisted feature table for transparency, but excluded from the
model's own inputs (`docs/experiments/ranking-model.md` has the evidence
for why):

| Feature | Used by the model? | What it measures |
|---|---|---|
| `retrieval_score` | Yes | Two-tower dot product for this (user, candidate) pair — the learned embedding-compatibility signal from the retrieval model, carried forward as one input among several. |
| `popularity` | No — computed, excluded | The popularity baseline's training click count (`docs/experiments/baselines.md`) for the candidate, log-transformed. |
| `category_match` | Yes | 1 if the candidate's category matches the user's single most common history category, else 0. |
| `content_similarity` | Yes | Cosine similarity between the candidate's TF-IDF vector and the mean TF-IDF vector of the user's history — reuses the content-similarity baseline's vectorizer (`docs/experiments/baselines.md`). |
| `user_history_length` | Yes | Count of real (non-padding) history items for this user — an honest cold-start proxy. |
| `hour_of_day` | Yes | Hour (0–23) extracted from this impression's own timestamp. |

Article freshness (named in the component description) is not included:
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
