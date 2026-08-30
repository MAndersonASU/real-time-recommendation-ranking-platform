# Durable-History Retrieval Fallback

SERVING-DURABLE-HISTORY-69's own dedicated evaluation
(`docs/engineering-review-register.md`). Implementation:
`src/recommender/evaluation/evaluate_durable_history_fallback.py`.
Tests: `tests/test_evaluate_durable_history_fallback.py`.
Machine-readable result:
[`durable-history-fallback.json`](../../reports/durable-history-fallback.json).

## What was broken, reproduced directly

Before this fix, the live retrieval query
(`recommender.serving.pipeline.recommend`) was built from
`lookup.recent.recent_clicked_items` -- Redis's own recent-click list --
and nothing else. A returning user with a real durable click history but
a genuinely healthy, merely empty Redis record (not an outage: simply no
live event yet) produced an empty history, a zero-norm two-tower user
vector, and the same global-popularity candidate pool as every other
such user, regardless of how different their real histories were.

Reproduced directly, interactively, against the real serving path before
any fix: six real users with a durable history of five or more clicks
each, served against a genuinely empty, isolated Redis store, received
only 3 distinct top-10 sets (10 distinct items total) among them.

## The fix

`recommender.serving.pipeline.select_retrieval_history` now chooses
exactly one history for the two-tower embedding, Faiss retrieval, and
content-similarity profile, in this order: a non-empty *usable* recent
Redis history first, then the user's bounded durable history
(`DurableUserFeatures.history_item_ids`, populated in
`compute_durable_features`) when Redis has nothing usable, then an
explicit empty history (real, disclosed global-popularity retrieval)
when neither exists. Recent and durable are never merged -- no tested
reconciliation rule exists for their overlap, ordering, or duplicate-
click semantics. The response's `retrieval_history_source` field
(`"recent"` / `"durable"` / `"global_popularity"`) reports which of the
three actually drove a given request.

## What this evaluation measures, and why it is separate from end-to-end

`end-to-end-evaluation.json`'s own isolated recent-feature store is
reconciled from each impression's point-in-time `history` field before
nearly every request (`recent_feature_coverage` there is 97.6%), so it
does not exercise the durable-only, empty-Redis path this fix addresses.
This evaluation isolates that path deliberately: a cohort of real
`validation`-split users who have a usable, catalog-valid, point-in-time
durable history, served through the real `safe_recommend()` path against
a fresh `InMemoryRedis` this run never seeds or writes to -- not
`use_recent_features=False` (a different, pre-existing ablation), and
not the shared serving context's own Redis client, whose real contents
this run does not control.

An impression is eligible only when its point-in-time durable history
(reconstructed the same leakage-free way `evaluate_end_to_end` builds
its own point-in-time durable features -- never a user's *latest* row in
the whole split) is non-empty after filtering to ids this catalog
actually has content for. A user whose `history` field is empty (a
genuinely new user) or, rarely, entirely off-catalog is excluded and
counted as such, not silently scored against an empty history -- but
this excludes only a small minority of sampled impressions in practice
(2.6%, 210 of the 8,000 sampled below), not most of them: most
validation-split users do have a usable point-in-time durable history,
so this evaluation's cohort is close to the general population, not a
rare subset of it.

## Results

K=10, 8,000 impressions drawn by seeded uniform sampling from the
30,270-impression validation split; 7,790 eligible (210 excluded for no
usable durable history), spanning 6,885 distinct users
(`reports/durable-history-fallback.json`).

| Metric | Result |
|---|---|
| Eligible impressions evaluated | 7,790 (of 8,000 sampled; 210 excluded) |
| Eligible users | 6,885 |
| Retrieval history source | 100% durable (7,790 of 7,790) |
| Distinct top-10 sets | 7,312 |
| Distinct recommended items | 7,780 |
| Catalog coverage@10 | 15.2% |
| Top-10 concentration | 0.10% |
| Mean pairwise slate Jaccard | 6.3% |
| Retrieval contained a click | 13.7% |
| Hit rate@10 | 0.81% |
| Recall@10 | 0.51% |
| NDCG@10 | 0.40% |
| MRR | 0.46% |

`retrieval_history_source` reporting 100% `"durable"` is not merely the
expected outcome -- it is asserted directly in
`tests/test_evaluate_durable_history_fallback.py`, so a future
regression that silently reintroduced a recent-history path into this
evaluation's isolated store would fail loudly here rather than quietly
invalidating what this report measures.

## A post-fix evaluation, not a measured before/after comparison

This report contains only post-fix results: 7,790 durable-only eligible
impressions produce 7,312 distinct served top-10 slates and 15.2%
catalog coverage. It does not include a matching pre-fix run at this
same scale and cohort -- no baseline arm was measured, so a real,
paired before/after comparison at 7,790 impressions does not exist yet.
The pre-fix behavior is established by code and by direct reproduction,
not by a matching measurement here: reading `select_retrieval_history`
before this fix shows every one of these 7,790 impressions would have
built its retrieval query from an empty history regardless (no durable
fallback existed), which produces a zero-norm embedding and the
identical flat-popularity candidate pool for every such user -- exactly
what the interactive reproduction above showed directly, for 6 real
users, before any fix (3 distinct slates, 10 distinct items). That
reproduction is real evidence of the pre-fix mechanism, not a
representative sample and not a quality estimate at this evaluation's
scale.

`distinct_top_k_sets` and `catalog_coverage_at_k` measure the final
served top-K slate (post-ranking, post-reranking), not the full
retrieval candidate pool (the ~1,000 candidates Faiss or the popularity
path hands to ranking) -- a genuine change in the served slate is
still informative, since a flat popularity pool feeding the same
ranking and reranking stages would deterministically produce the same
slate for every historyless user, which the pre-fix code and
reproduction both establish it did. But it is not itself a direct
measurement of candidate-pool diversity, only of what was ultimately
served. A rigorous paired before/after comparison -- a real pre-fix
baseline arm on this identical cohort, recording both the full
retrieval candidate pools and the final served slates for baseline
versus durable-history treatment -- would be the stronger evidence and
is not attempted here.

## Interpretation and limitations

Hit rate, recall, NDCG, and MRR here are low in absolute terms, matching
the same order of magnitude as `end-to-end-evaluation.json`'s own
figures on a different cohort -- consistent with this project's
established difficulty finding the one specific clicked article in a
51,282-item catalog from history alone, not a defect specific to this
evaluation. This report does not claim retrieval from durable history
matches retrieval from a real recent history in quality; it claims only
that durable-history retrieval is real, personalized, and measurably
distinct from the flat
popularity pool every durable-only user used to receive regardless of
who they were, which is the exact defect SERVING-DURABLE-HISTORY-69
names.

"Usable durable history" means what MIND's own `history` field recorded
for a user as of one impression, which is itself already bounded and
does not document how far back it extends -- not necessarily a user's
complete real history. Retrieval is the binding constraint here, as
elsewhere in this project: no ranking improvement can lift the reported
figures above `retrieval_contained_a_click_rate`. This evaluation
measures the durable-only fallback path in isolation, by construction
(the isolated Redis is never seeded); it does not measure how often a
live deployment's real users actually reach this path versus a real
recent-history one -- `end-to-end-evaluation.json`'s own
`recent_feature_coverage` is the figure for that separate question. Does
not reproduce production traffic, concurrency, or infrastructure
latency.
