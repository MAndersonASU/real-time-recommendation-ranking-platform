# Research conclusions

This page answers the five research questions defined in
[the research scenario](research-scenario.md). It adds no new
measurement. Every number comes from a published document and its JSON
report.

## Short answer

| Question | Answer |
|---|---|
| Do learned embeddings help retrieval? | They improved the original retriever, but full-catalog retrieval remains weak. |
| Does learned ranking help? | Yes. This is the clearest relevance gain. |
| Does reranking improve diversity and freshness? | Yes, with a small relevance cost and slightly lower catalog coverage. |
| Do recent streaming features help quality? | Not demonstrated in the available replay, because Redis was empty for the measured sample. |
| What is the latency and quality tradeoff? | Reranking costs the most latency and buys diversity/freshness; the ranker buys relevance at a smaller latency cost. |

## RQ1: Do learned embeddings help retrieval?

**Answer: they improved this retriever, but did not make it strong.**

The original item tower represented an article only by category and
subcategory. As a result, 51,282 articles collapsed into 284 distinct
vectors. Full-catalog retrieval at N=100 produced a hit rate of 0.0044.

Adding title and abstract content increased the catalog to 50,704
distinct vectors. The four relevance metrics—hit rate, recall, NDCG,
and MRR—improved by 7.6x to 13.5x. Hit rate@100 rose from 0.0044 to
0.0336. Catalog coverage improved separately by 1.5x.

The isolated retrieval test uses N=100. Current serving retrieves 1,000
candidates. In the end-to-end serving evaluation, the clicked item
reached that candidate pool 14.14% of the time, and the final hit
rate@10 was 0.84%.

These measurements agree on the main point: the content change removed
the known vector-collapse problem, but retrieval is still the system's
largest quality constraint. The remaining cause has not been isolated.

Evidence:
[retrieval model](experiments/retrieval-model.md),
[retrieval evaluation](experiments/retrieval-evaluation.md), and
[end-to-end evaluation](experiments/serving-path-end-to-end-evaluation.md).

## RQ2: Does learned ranking help?

**Answer: yes, under the candidate-list protocol.**

On the same candidate lists, learned ranking beat sorting by the raw
retrieval score:

| Metric | Retrieval score | Learned ranking |
|---|---:|---:|
| Hit rate@10 | 0.6689 | **0.6828** |
| NDCG@10 | 0.3518 | **0.3671** |

It also beat the non-learned baselines. Removing `retrieval_score` from
the ranking inputs reduced hit rate by 3.5% and NDCG by 3.4%. The
embedding score is therefore useful to the ranker even though it is not
strong enough to solve full-catalog retrieval alone.

This is development evidence, not a final generalization estimate,
because no untouched test split remains.

Evidence:
[ranking evaluation](experiments/ranking-evaluation.md) and
[ablations](experiments/ablations.md).

## RQ3: Does reranking improve diversity and freshness?

**Answer: yes, with a measured relevance tradeoff.**

Reranking changed the final slate as follows:

- mean distinct categories: 4.70 to 5.42, a 15.1% increase;
- slates below the freshness quota: 82.0% to 74.0%, a 9.8% relative
  reduction;
- relevance: no more than about a 2.6% decrease on any reported metric;
- catalog coverage: a 3.8% decrease.

The catalog-coverage result is not a contradiction. The policy improves
variety inside one impression's candidate list. It does not guarantee
that more unique items appear across all impressions.

Evidence: [reranking evaluation](experiments/reranking-evaluation.md).

## RQ4: Do recent streaming features improve quality?

**Answer: the available replay did not demonstrate a quality gain.**

The measured hit rate was identical with recent features enabled or
disabled. The real Redis store had been flushed, so neither arm found a
recent record. Both used the same durable-history or global-popularity
source, leaving no difference for the toggle to measure.

The Redis attempt still had a latency cost. Mean feature lookup fell
from 1.78 ms to 0.012 ms when the lookup was disabled. The isolated
Redis benchmark measured 0.29 ms p50.

This result does not show that recent behavior is useless. It shows that
an empty-state replay cannot answer the question. A population with
accumulated Redis state or continuous live traffic is required.

Evidence:
[ablations](experiments/ablations.md) and
[state store](operations/state-store.md).

## RQ5: What is the latency and quality tradeoff?

| Component removed or changed | Quality effect | Latency effect |
|---|---|---|
| Retrieval score in ranking | Hit rate −3.5%, NDCG −3.4% | None measured |
| Other ranker inputs | Hit rate about −2.0%, NDCG about −4.1% | About 1.73 ms p50 saved |
| Reranking | Relevance rises; diversity and freshness fall | About 10.63 ms p50 saved |
| Recent Redis features | No measured change in the empty-state sample | 1.78 ms to 0.012 ms |
| Approximate index setting | Recall 0.624 at nprobe=8 | About 12.6x faster than exact |

Reranking is the largest current latency component and produces the
diversity/freshness gain. The ranker produces the clearest relevance
gain at a smaller latency cost.

Candidate retrieval used to dominate latency. It became cheaper after
durable user history was used when Redis had no recent record, avoiding
the expensive full-catalog cold-start popularity path for many
returning users.

Evidence:
[serving latency](experiments/serving-latency.md) and
[ablations](experiments/ablations.md).

## Combined candidate-list result

| Model output | Hit rate@10 | Change |
|---|---:|---:|
| Content-similarity baseline | 0.6557 | — |
| Retrieval score | 0.6689 | +0.0132 |
| Learned ranking | 0.6828 | +0.0139 |
| Ranking plus reranking | 0.6675 | −0.0153 |

Ranking contributes most of the relevance gain over the strongest
baseline. Reranking deliberately spends part of that gain on diversity
and freshness.

## Where misses concentrate

Across 30,270 impressions, the miss rate was 33.3%.

- Cold-start users missed 43.9% of the time.
- Users with long histories missed 32.2% of the time.
- Clicks outside the user's dominant category missed 35.0% of the time.
- Clicks inside that category missed 28.7% of the time.

An apparently surprising result—never-clicked training items missing
less often than warm items—was explained by impression size. Warm-item
clicks appeared in larger, more competitive lists. The model's average
predicted score was almost the same for both groups.

Evidence: [failure analysis](experiments/failure-analysis.md).

## What the project also demonstrates

Beyond recommendation quality, the project verifies:

- a containerized API with separate health and readiness checks;
- request-correlated JSON logs and Prometheus metrics;
- a compact operational dashboard;
- Kafka replay and Redis state updates;
- restart, redelivery, fallback, and dependency-failure behavior;
- two measured single-machine optimizations for throughput and memory.

These are engineering results, not evidence of production scale.

## Where the evidence ends

- No live A/B test was run.
- MIND clicks reflect the exposure policy of the original news system.
- No untouched final test split remains.
- Recent-feature value under continuous traffic is unknown.
- Workloads large enough to require horizontal scaling or sharded
  embedding tables were not tested.
- Retrieval remains weak after the known representation problem was
  removed.

The most important conclusion is therefore narrow: this project shows
how the components behave under its documented offline protocols. It
does not establish live user impact or production readiness.
