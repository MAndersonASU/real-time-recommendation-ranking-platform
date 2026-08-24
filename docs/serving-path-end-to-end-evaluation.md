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
come only from an isolated, in-run state store — seeded from that same
point-in-time `history` field and updated with an impression's own
events only after that impression has already been scored.
Implementation:
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

Chronologically-earliest validation impressions, K=10.

| Metric | 500 impressions | 2,000 impressions |
|---|---|---|
| Impressions evaluated | 500 (0 skipped) | 2,000 (0 skipped) |
| Durable-feature coverage | 100% | 100% |
| Recent-feature coverage | 97.8% | 97.8% |
| Fallback count | 0 | 0 |
| Catalog coverage | 2.3% | 3.9% |
| **Retrieval contained a click** | **0.2%** | **0.2%** |
| Hit rate@10 | 0.0 | 0.0005 |
| Recall@10 | 0.0 | 0.00025 |
| NDCG@10 | 0.0 | 0.00013 |
| MRR | 0.0 | 0.000125 |

Ranking quality is effectively zero, and the row that explains it is
`retrieval_contained_a_click`: the item the user actually clicked was
among the 50 retrieved candidates in only 0.2% of impressions. That is
a hard ceiling — the end-to-end hit rate cannot exceed it no matter how
good ranking becomes. At 2,000 impressions the clicked item was
retrieved 4 times and ranked into the top 10 once. The bottleneck is
candidate generation, not ranking or reranking, and this run measures
that directly rather than leaving it inferred.

### A real evaluation bug found and fixed while producing these numbers

An earlier version of this evaluation reported 8.2% recent-feature
coverage and 0.6% catalog coverage. Both were artifacts of a real bug
in the harness, not properties of the serving path.

The isolated state store started empty for every user, so any
impression whose user had no *earlier in-window* event was scored with
an empty recent-click list. `recommend()` builds its two-tower query
from that list, and `TwoTowerModel.user_vector` averages the item
vectors of the history — an empty history sums to exactly zero. An
inner-product Faiss index scores every catalog item identically against
a zero vector, so retrieval returned an arbitrary tie order, the same
one for every history-less user, and the ranking model then saw a
constant `retrieval_score` and assigned every candidate the same
probability. Measured directly: 60 impressions produced **1** distinct
candidate set under the empty store versus **50** once real history was
supplied.

MIND records, per impression, the clicks that happened strictly before
it, so seeding the store from that field is point-in-time correct
rather than leakage — it is exactly what a live store would already
hold for a returning user. With the fix, recent-feature coverage rises
to 97.8% and catalog coverage roughly quadruples. **The ranking metrics
did not materially improve**, because the retrieval ceiling above is
the real constraint; the fix makes this evaluation measure the actual
serving path instead of a degenerate one, which is its own reason to
have made it.

The same zero-vector condition was a real defect on the live serving
path too, not only in evaluation — see `docs/serving-fallback.md` for
the cold-start retrieval change it prompted.

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

Durable- and recent-feature coverage are both high by construction now
(each is computed from the impression's own `history` field, which MIND
provides for essentially every row) — a real change in what those
numbers mean compared to a cache-hit-rate interpretation, not a claim
that personalization quality improved. Catalog coverage (2.3–3.9%)
reflects the same collapsed-embedding-space limitation described above.

One further measured factor, reported but deliberately not acted on:
the serving path retrieves 50 candidates out of 51,282
(`RETRIEVAL_MULTIPLIER` × K, floored at `MIN_RETRIEVAL_CANDIDATES`).
Measuring the clicked item's rank under full-catalog retrieval gives a
median rank of 11,779 — better than the ~25,600 random chance would
predict, so the model has learned something real — with recall@50 of
about 2% rising to about 16% at depth 1,000. Retrieving deeper would
therefore put the clicked item in front of the ranker substantially
more often. That is a hyperparameter choice, and
`docs/evaluation-integrity.md` records why this project no longer makes
such choices by looking at `validation` and then reporting against it.
Changing retrieval depth on the strength of the numbers above would be
exactly that mistake, so the finding is recorded here and left for a
decision made against the tuning fold instead.

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
