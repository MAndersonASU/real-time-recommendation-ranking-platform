# Final Research Conclusions

Synthesizes what every the preceding work already measured into one final
answer for each research question, plus the costs this project
introduced and where the evidence deliberately stops short of a claim
it can't support. Nothing here is a new measurement — every claim below
traces back to a specific already-published doc or a run already
logged locally in `data/processed/mind_small/experiment_log.jsonl`,
which is not committed; the published equivalents are in `reports/`
(`docs/experiment-tracking.md`).

## RQ1: Do learned embeddings help retrieval?

A measured improvement over the original architecture, still
short of competitive retrieval quality.

The first answer recorded here was "not demonstrated": full-catalog
retrieval (N=100) scored a 0.0044 hit rate, barely above the ~0.2%
random-chance floor, because the item tower encoded each article purely
from category and subcategory and so produced only 284 distinct
embedding vectors across 51,282 items — it had no way to tell two
articles in the same category apart.

That diagnosis was specific and testable, and fixing the diagnosed
cause moved every retrieval metric by 7.6x to 13.5x (hit rate@100
0.0044 → 0.0336; distinct embeddings 284 → 50,704). Each article now
carries a content vector derived from its own title and abstract
(`docs/retrieval-model.md`, `docs/retrieval-evaluation.md`).

It is still not a working retriever in a deployable sense: the user's
real next click is absent from a 100-item candidate set roughly 97% of
the time. **Answer: not
demonstrated by this architecture, for a diagnosed and fixable reason
(item-tower feature richness), not a verdict on learned embeddings in
general.**

## RQ2: Does a learned ranker add value beyond retrieval?

Yes, clearly, the strongest positive result in this project. Over the
same frozen candidate pool, the ranking model beat sorting by raw
retrieval score alone on every relevance metric (hit rate 0.6828 vs.
0.6689, NDCG 0.3671 vs. 0.3518 — `docs/ranking-evaluation.md`), and
beat every non-learned baseline too. The
retrieval-feature ablation (`docs/ablations.md`) confirms this isn't
just the ranker's other features doing the work: removing
`retrieval_score` from the ranker's own inputs cost measurable ground
(hit rate −3.5%, NDCG −3.4%), so the two-tower signal is useful input to
a ranker even where it was too weak to drive full-catalog retrieval
alone. **Answer: development evidence under the candidate-list protocol
supports this.** No untouched final split remains, so this is not a
generalization estimate.

## RQ3: Does reranking improve diversity and freshness?

Yes, at a real, small, disclosed relevance cost. Reranking raised mean
distinct categories per slate from 4.50 to 5.33 (+18.3%) and cut the
fraction of slates below the freshness quota from 13.3% to 4.8% (−64%
relative), at a relevance cost under 2.2% on every metric
(`docs/reranking-evaluation.md`). Catalog coverage moved slightly the
wrong way (−2.3%), a disclosed, understood exception: the diversity
policy only reshuffles within one impression's own already-narrow
candidate pool, so within-impression variety and across-impression
catalog coverage are two genuinely different properties that don't
automatically move together. **Answer: yes, with one honestly stated
exception.**

## RQ4: Do recent streaming features help?

Real infrastructure cost measured; no quality benefit measurable in
this replay sample. The ablation (`docs/ablations.md`) found identical
hit rate (0.0) with and without recent features — but that floor was
already independently explained: this replay population is measured at
92.4% durable cold start and 0% live-Redis coverage
(`docs/limitations.md`), leaving no headroom for recent features to
show a difference either way. What is measurable is the
latency cost of having them: removing the Redis round-trip cut mean
feature-lookup time from 0.80ms to 0.008ms, consistent with the
isolated Redis benchmark measured when the store was first built
(0.29ms p50, `docs/state-store.md`). **Answer: not demonstrated to
help in this particular sample, for a reason (extreme cold start) that
is itself a limitation of the sample, not evidence the feature is
worthless. A population with genuine, continuous live traffic would be
needed to answer this question properly.**

## RQ5: What does the latency/quality tradeoff actually look like?

| Component removed | Quality cost | Latency saved |
|---|---|---|
| Retrieval features | Hit rate −3.5%, NDCG −3.4% | None measured |
| Ranker features | Hit rate −2.9%, NDCG −6.1% | ~1.49ms p50 |
| Reranking | Relevance rises (+1.8%/+1.4%), diversity/freshness fall | ~8.88ms p50 (69% of total) |
| Recent streaming features | Unchanged in this sample | 0.80ms→0.008ms |
| Cache/index settings | Recall 0.624 at nprobe=8 | ~12.6x faster than exact |

Reranking is both the single largest latency cost in the system and
one of its two real quality wins (diversity/freshness) — the two are
directly in tension, and this table is the first place that tension is
shown in one place rather than argued about qualitatively. Full detail:
`docs/ablations.md`.

## The cumulative pipeline gain, stage by stage

| Stage | Hit rate@10 | Δ from prior stage |
|---|---|---|
| Best baseline (content similarity) | 0.6557 | — |
| + Retrieval score as sort key | 0.6689 | +0.0132 |
| + Learned ranking model | 0.6828 | +0.0139 |
| + Reranking (diversity/freshness) | 0.6675 | −0.0153 |

Ranking is where most of the pipeline's real, cumulative gain over the
strongest non-learned baseline comes from. Retrieval alone
adds a small amount on hit rate but *loses* ground on NDCG (−0.0008,
[`docs/stage-comparison.md`](stage-comparison.md)) — true in the underlying numbers the
whole time, only visible once every stage sat side by side in one
table. Reranking spends part of the ranking model's gain, deliberately,
on the diversity/freshness improvement documented under RQ3.

## Where the system actually fails (docs/failure-analysis.md)

Overall miss rate 33.2% across 30,270 real impressions. Misses
concentrate predictably by user history depth (43.5% for a cold-start
user vs. 31.9% for a well-established one) and by whether the clicked
item's category matched the user's own dominant history category
(35.1% vs. 28.3%) — both consistent with what the ranking model was built to use. One counter-intuitive result was chased down
rather than reported at face value: items never clicked in training
miss *less* often than items that were, explained not by the model
treating them differently (its own predicted score is nearly identical
either way) but by impression size — a warm item's real click tends to
land in a larger, more competitive impression, diluting its odds purely
through more rivals for the same 10 slots.

## What this project cost to build

measured, not estimated: a containerized HTTP service with
health/readiness separation and CI-verified failure-path behavior
(`docs/containerization.md`, `docs/restart-and-failure-testing.md`); a
`/metrics` endpoint, a rolling ML-quality tracker, structured
request-correlated JSON logging, and a compact operational dashboard
(`docs/operational-metrics.md`, `docs/ml-quality-signals.md`,
`docs/structured-logging.md`, `docs/dashboard.md`); real load-tested
concurrency behavior and two evidence-justified optimizations that
measurably improved throughput and memory footprint
(`docs/optimization.md`). None of this was added speculatively — every
piece traces to a measured need identified by the work that built
it.

## Where the evidence deliberately stops

- **No live A/B test was ever run**, by explicit, frozen scope
  (`docs/research-scenario.md`). Every relevance number in this project
  measures agreement with MIND's own already-deployed system's past
  choices, never a genuinely different candidate set's real outcome
  (`docs/limitations.md`).
- **Richer item features were implemented and evaluated.** The item
 tower was reopened and given per-article content vectors; distinct
 catalog embeddings rose from 284 to 50,704 and retrieval metrics
 improved 7.6x-13.5x
 ([`docs/retrieval-evaluation.md`](retrieval-evaluation.md)). That
 removed the tie ceiling. Absolute retrieval quality remains low, and
 what explains the remaining gap is untested.
- **Whether recent streaming features would show measurable value**
  against a population with continuous real traffic, rather than the
  extreme cold start this project's replay sample happens to have, is
  genuinely unanswered by anything measured here.
- **Scale beyond MIND-large on a single machine** was profiled and
  optimized (`docs/optimization.md`, `docs/distributed-evaluation.md`)
  but never tested against a workload large enough to make horizontal
  scaling or a sharded embedding table (TorchRec) actually necessary —
 the measured bottleneck throughout was single-machine CPU
  saturation, not embedding table size.
