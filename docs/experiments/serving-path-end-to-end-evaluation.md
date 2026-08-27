# Serving-Path End-to-End Evaluation

`docs/experiments/ranking-features.md` already discloses a deliberate methodological
choice: the ranking model is evaluated against MIND's own frozen
impression candidate list, not against the retrieval model's own top-N
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
time state — not a claim about serving-path traffic, real request
concurrency, real Kafka/Redis latency, or the real cadence a durable-
feature batch job would run on.

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

## Results

K=10, 5,000 impressions drawn by seeded uniform sampling from the
30,270-impression validation split
(`reports/end-to-end-evaluation.json`).

| Metric | Result |
|---|---|
| Impressions evaluated | 5,000 (0 skipped) |
| Distinct users | 4,612 |
| Durable-feature coverage | 100% |
| Recent-feature coverage | 97.6% |
| Fallback count | 0 |
| Catalog coverage | 12.5% |
| **Retrieval contained a click** | **14.1%** |
| Hit rate@10 | **0.0084** |
| Recall@10 | **0.0054** |
| NDCG@10 | **0.0042** |
| MRR | **0.0048** |

### The sample used to be a prefix, and that mattered

Earlier versions of this table reported the chronologically *earliest*
2,000 impressions, selected with `head(2000)`. That is not a sample of
the split: it covers roughly the first hour of a single day and
whichever users happened to be active in it. Selection is now a seeded
uniform draw across the whole split, which spans 00:02 to 23:58 and
4,612 distinct users.

The correction was not cosmetic. Against the old prefix the same system
measured:

| Metric | Prefix, n=2,000 | Representative, n=5,000 |
|---|---|---|
| Retrieval contained a click | 12.2% | **14.1%** |
| Hit rate@10 | 0.0145 | **0.0084** |
| NDCG@10 | 0.0061 | **0.0042** |
| MRR | 0.0074 | **0.0048** |

The prefix **overstated end-to-end hit rate by about 1.7x**. Note that
the two directions disagree: retrieval looks *better* on the
representative sample while every downstream metric drops. So the
earliest impressions were not uniformly easier — they were harder to
retrieve for and easier to rank within, and a prefix cannot show that
because it holds the confound fixed. The published figures above are
the representative ones.

A further caveat on precision, now that it is visible: at a hit rate
near 1%, the metric rests on a few dozen hits even at n=5,000. Sample
size was raised from 500 for exactly this reason. Variance across
several seeds has not been measured, so these figures are reproducible
— the seed is recorded — but their sampling error is not quantified.

`retrieval_contained_a_click` is the row that explains the rest: it
reports how often the item the user actually clicked was among the
candidates retrieval handed to the ranker. It is a hard ceiling, since
ranking cannot promote an item it never received. Raising it from 0.2%
to 14.1% is what moved every metric below it.

Three separate changes produced this, and they are worth keeping
distinct rather than credited as one:

1. **The item tower gained per-article content features**, ending the
   284-distinct-vector collapse (`docs/experiments/retrieval-evaluation.md`).
2. **Retrieval depth rose from 50 to 1,000 candidates**, decided on the
   tuning fold rather than on `validation`
   (`docs/experiments/evaluation-integrity.md`).
3. **Two zero-vector defects were fixed**, described immediately below.

Absolute quality remains low and should be read as such: a hit rate of
0.84% means this system puts the user's real next click in a ten-item
slate about once in every 119 impressions. That is a large relative
improvement on a genuinely hard task (ten items chosen from 51,282), not
a competitive recommender.

### A real evaluation bug found and fixed while producing these numbers

An earlier version of this evaluation reported 8.2% recent-feature
coverage and 0.6% catalog coverage. Both were artifacts of a bug
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
path too, not only in evaluation — see `docs/operations/serving-fallback.md` for
the cold-start retrieval change it prompted.

## Reading these numbers honestly

`docs/experiments/retrieval-evaluation.md` originally measured hit rate@100 at
0.0044 against the full catalog and traced it to a named architecture
limitation: the item tower's category/subcategory-only features
collapsed 51,282 items into 284 distinct embedding vectors
(`docs/archive/faiss-index.md`). That limitation propagated through this whole
pipeline — ranking and reranking cannot recover a click that retrieval's
candidate set never contained — which is why every metric here was once
effectively zero. It was one problem observed twice, not two problems.

That cause has since been fixed rather than restated, and the numbers
above are the result. What remains true, and should not be smoothed
over:

- **This is still not a competitive recommender.** Hit rate@10 of 0.84%
  means the user's real next click reaches their slate roughly once in
  119 impressions.
- **Retrieval is still the binding constraint.** The clicked item
  reaches the ranker 14.1% of the time, so no ranking or reranking work
  can lift the end-to-end result past that ceiling. Further gains have
  to come from retrieval quality, not from the stages after it.
- **Coverage numbers mean something specific here.** Durable- and
  recent-feature coverage are high by construction, since both derive
  from each impression's own `history` field, which MIND provides for
  essentially every row. That is a statement about reconstruction
  fidelity, not about personalization quality.
- **Retrieval depth was changed deliberately, and not on this split.**
  Raising it from 50 to 1,000 candidates was decided against the tuning
  fold (`verify_retrieval_depth`), because choosing a hyperparameter by
  looking at `validation` and then reporting against `validation` is
  precisely the leakage `docs/experiments/evaluation-integrity.md` exists to record.
  The cost is real and measured: about 4 ms of additional end-to-end p50
  latency, since ranking and reranking both scale with candidate count
  even though index search itself stays under a millisecond.

## Status and limitations

The point-in-time-correctness gaps found in review — durable features
leaking a user's future history, recent features depending on ambient
shared Redis state, and an empty seed producing a degenerate zero-vector
query — are fixed and covered by regression tests proving chronological
state evolution, isolation from the shared serving context, determinism,
correct seeding, and the absence of future leakage.

What this evaluation still does *not* establish: serving-path traffic
patterns, concurrency, or infrastructure latency; a durable-feature
refresh cadence matching any real deployment plan; or that the ranking
quality reported above is adequate for any real use. It is reported
alongside — not in place of — the frozen-candidate-list protocol, since
the two measure genuinely different things and neither supersedes the
other.
