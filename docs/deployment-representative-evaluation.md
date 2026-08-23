# Deployment-Representative Ranking Evaluation

`docs/ranking-features.md` already discloses a deliberate methodological
choice: the ranking model is evaluated against MIND's own frozen
impression candidate list, not against Phase 3 retrieval's own top-N
output, specifically to isolate RQ1 (is retrieval any good) from RQ2
(does ranking improve on a candidate set). That choice is real, still
valid for what it measures, and is not changed here.

What was missing until now: no evaluation ever ran the real, full
`/recommend` pipeline end to end — retrieval, ranking, and reranking
together, exactly what a live request executes — and checked whether a
real validation user's real recorded click ended up in the real
returned slate. The frozen-candidate-list protocol answers "does the
ranking model help, given a candidate set," never "what does a real
user of this deployed system actually get." Both questions are
legitimate; only one had an evaluation. Implementation:
`src/recommender/evaluation/evaluate_end_to_end.py`. Tests:
`tests/test_evaluate_end_to_end.py`.

## What it does

For a sample of real `validation`-split impressions with a real click,
builds a real `RecommendationRequest` (real user ID, real historical
impression time) and calls the real `safe_recommend()` — the same
function `/recommend` calls — then scores the returned slate against
the real click using the same metric functions already hand-verified
for retrieval's own top-N evaluation (`recall_at_n_known_total`,
`ndcg_at_n_known_total`, since a Faiss-retrieved top-K slate is a
top-N slice of the full catalog, not the complete frozen impression
list the original protocol scores).

## Real result

500 validation impressions (the same sampling tradeoff
`evaluate_via_replay` and `build_index.py`'s benchmark already made —
each call is a real, full pipeline invocation), K=10, 0 fallbacks (the
real path ran for every request, never the popularity safety net).

| Metric | Value |
|---|---|
| Hit rate@10 | 0.0 |
| Recall@10 | 0.0 |
| NDCG@10 | 0.0 |
| MRR | 0.0 |

## This is not a new defect — it is the already-diagnosed retrieval limitation, confirmed end to end

`docs/retrieval-evaluation.md` already measured hit rate@100 at 0.0044
against the full catalog and traced it to a specific, named architecture
limitation: the item tower's category/subcategory-only features collapse
51,282 catalog items into 284 distinct embedding vectors
(`docs/faiss-index.md`), so retrieval can identify the right cluster but
has no signal at all to pick the right item within it. At K=10 — a
narrower slice than the N=100 that measurement used — the expected
number of hits across 500 sampled impressions is close enough to zero
that observing exactly zero is consistent with that already-measured
rate, not a new or different failure. Ranking and reranking cannot
recover a click that retrieval's candidate set never contained in the
first place; this result is the same limitation propagating through the
full pipeline, not a second, independent problem.

## Honest interpretation

This evaluation does not change RQ1's or RQ2's answer. It confirms, via
the actual deployed code path rather than an isolated retrieval-only
measurement, that a real user of this system today would not reliably
receive their real next click in their slate — a fact `docs/retrieval-
evaluation.md` already stated plainly for retrieval alone, now also
verified true of the assembled system a user actually calls. The fix is
the same one already named and scoped there: enrich the item tower with
per-article features, not something reopened or re-scoped by this
finding.

## Status

Verified resolved: a real, deployment-representative end-to-end
evaluation now exists, is tested, and has been run against real data and
the real trained artifacts. It is reported here alongside — not in place
of — the frozen-candidate-list protocol, since the two measure genuinely
different things and neither should be read as superseding the other.
