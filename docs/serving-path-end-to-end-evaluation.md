# Serving-Path End-to-End Evaluation

`docs/ranking-features.md` already discloses a deliberate methodological
choice: the ranking model is evaluated against MIND's own frozen
impression candidate list, not against Phase 3 retrieval's own top-N
output, specifically to isolate RQ1 (is retrieval any good) from RQ2
(does ranking improve on a candidate set). That choice is real, still
valid for what it measures, and is not changed here.

What this adds: a run of the real `/recommend` code path — retrieval,
ranking, and reranking together — against real, chronologically ordered
validation-split impressions, with point-in-time-correct state: each
impression's durable features come only from that impression's own
`history` field (never a later impression's), and its recent features
come only from an isolated, in-run state store that starts empty and is
updated with an impression's own events only after that impression has
already been scored. Implementation:
`src/recommender/evaluation/evaluate_end_to_end.py`. Tests:
`tests/test_evaluate_end_to_end.py`.

This is a name change from an earlier version of this document, which
called this a "deployment-representative" evaluation. That term
overstated what it measures: this is a real run of the serving code
path against real historical data with real, reconstructed point-in-
time state — not a claim about real production traffic, real request
concurrency, real Kafka/Redis latency, or the real cadence a durable-
feature batch job would actually run on.

## What it does

For a sample of real `validation`-split impressions, sorted into real
chronological order, each with a real click: builds a real
`RecommendationRequest` (real user ID, real historical impression time)
using durable features computed fresh from that one impression's own
`history` field and recent features read from an isolated store
containing only strictly earlier events from this same run, calls the
real `safe_recommend()` — the same function `/recommend` calls — scores
the returned slate against the real click, then applies this
impression's own events to the isolated store so a later impression can
see them. Uses the same metric functions already hand-verified for
retrieval's own top-N evaluation (`recall_at_n_known_total`,
`ndcg_at_n_known_total`, since a Faiss-retrieved top-K slate is a
top-N slice of the full catalog, not the complete frozen impression
list the original protocol scores).

## Real result

500 chronologically-earliest validation impressions, K=10.

| Metric | Value |
|---|---|
| Impressions evaluated | 500 (0 skipped) |
| Durable-feature coverage | 100% |
| Recent-feature coverage | 8.2% |
| Fallback count | 0 |
| Catalog coverage | 0.6% |
| Hit rate@10 | 0.0 |
| Recall@10 | 0.0 |
| NDCG@10 | 0.0 |
| MRR | 0.0 |

Reported honestly, not smoothed over: every ranking-quality metric is
zero. This is not new evidence being hidden behind a passing label —
see the next section for what it does and does not mean.

## This is not a new defect — it is the already-diagnosed retrieval limitation, run end to end

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

Two numbers in this run are worth reading honestly rather than at face
value. Durable-feature coverage is 100% by construction now (it is
computed directly from each impression's own `history` field, which
MIND provides for essentially every row) — a real change in what this
number means compared to a cache-hit-rate interpretation, not a claim
that personalization quality itself improved. Recent-feature coverage
(8.2%) and catalog coverage (0.6%) are both realistically low for this
specific run: recent state only exists once a user has already
appeared earlier in this same 500-impression sample, and catalog
coverage reflects the same collapsed-embedding-space limitation
described above, not a separate bug.

## Honest interpretation

This evaluation does not change RQ1's or RQ2's answer. It confirms, via
the actual serving code path rather than an isolated retrieval-only
measurement, that a real user of this system today would not reliably
receive their real next click in their slate at K=10 — a fact
`docs/retrieval-evaluation.md` already stated plainly for retrieval
alone, now also observed to hold true of the assembled system's own
code path under point-in-time-correct state reconstruction. The fix is
the same one already named and scoped there: enrich the item tower with
per-article features, not something reopened or re-scoped by this
finding.

## Status and limitations

The point-in-time-correctness gap a follow-up review found (durable
features leaking a user's future history, recent features depending on
ambient shared Redis state) is fixed and covered by regression tests
proving chronological state evolution, isolation from the shared
serving context, determinism, and the absence of future leakage. What
this evaluation does *not* establish: real production traffic patterns,
concurrency, or infrastructure latency; a durable-feature refresh
cadence matching any real deployment plan; or an improvement to the
zero ranking-quality result itself, which remains an open, disclosed
limitation of retrieval's current item-tower architecture. Reported
here alongside — not in place of — the frozen-candidate-list protocol,
since the two measure genuinely different things and neither should be
read as superseding the other.
