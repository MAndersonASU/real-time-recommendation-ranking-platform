# End-to-end serving evaluation

Source:
[`reports/end-to-end-evaluation.json`](../../reports/end-to-end-evaluation.json).

This evaluation calls the same `safe_recommend()` path as the API:
retrieval, ranking, and reranking together. It uses real historical
validation impressions and reconstructed point-in-time feature state.

Implementation:
`src/recommender/evaluation/evaluate_end_to_end.py`.
Tests: `tests/test_evaluate_end_to_end.py`.

## How the run works

For each sampled impression, in chronological order:

1. Build durable features from that impression's own prior history.
2. Reconstruct recent features in an isolated store using only history
   and earlier events available at that time.
3. Call `safe_recommend()` with the real user and impression time.
4. Score the returned top 10 against the recorded click.
5. Apply the impression's events so later impressions can see them.

Events sharing one timestamp are scored before any event from that
timestamp updates state.

This is a historical serving-code simulation. It does not reproduce
live traffic, concurrency, Kafka or Redis network latency, or a real
durable-feature refresh schedule.

## Current result

K=10. A seeded uniform sample selects 5,000 of the 30,270 validation
impressions.

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

The clicked article reaches the ranker in 14.1% of impressions and the
final top 10 in 0.84%. Put another way, the final slate contains the
recorded click about once per 119 impressions.

Retrieval containment is a hard ceiling. Ranking cannot promote an
article that retrieval did not return.

## Why the sample changed

An older run selected `head(2000)` after chronological sorting. That
was the earliest hour of the day, not a representative sample.

| Metric | Prefix, n=2,000 | Representative, n=5,000 |
|---|---|---|
| Retrieval contained a click | 12.2% | **14.1%** |
| Hit rate@10 | 0.0145 | **0.0084** |
| NDCG@10 | 0.0061 | **0.0042** |
| MRR | 0.0074 | **0.0048** |

Uniform sampling increased retrieval containment but reduced every
downstream measure. The old prefix overstated hit rate by about 1.7×.

The recorded seed makes this sample repeatable. Variation across
multiple seeds has not been measured, so sampling uncertainty remains
unquantified.

## Corrections behind the current result

Three model and configuration changes increased clicked-item
containment:

- article text features removed the 284-vector item-tower collapse;
- retrieval depth increased from 50 to 1,000 using tuning-fold
  evidence; and
- empty-history zero-vector behavior was corrected.

The evaluation harness itself also had a zero-vector defect. Its recent
store began empty, so many returning users looked historyless even
though MIND supplied their prior history. Sixty impressions produced
only one distinct candidate set under that design, compared with 50
after correct seeding.

Seeding from an impression's own prior history is time-safe because MIND
records that history before the impression. Recent-feature coverage is
now 97.6%. Live featureless users use an explicit popularity fallback
instead of querying Faiss with a zero vector.

## Metric definitions

The returned slate is a slice of the full catalog. Recall and NDCG use
the known number of clicked articles from the original impression
through `recall_at_n_known_total` and
`ndcg_at_n_known_total`.

Durable and recent feature coverage measure successful state
reconstruction. They do not measure recommendation quality.

Catalog coverage measures distinct articles in the final served slates,
not all retrieved candidates.

## What the result supports

- The complete serving code can be evaluated with chronological,
  isolated feature state.
- The current system remains weak in absolute quality.
- Retrieval remains the main constraint.
- Increasing depth to 1,000 costs about 4 ms in median end-to-end
  latency compared with depth 50.
- Candidate-list ranking results and end-to-end results answer different
  questions; neither replaces the other.

Validation already informed design choices, so this is post-selection
development evidence rather than a final generalization estimate.

Related pages:

- [candidate-list ranking](ranking-evaluation.md);
- [retrieval evaluation](retrieval-evaluation.md);
- [evaluation integrity](evaluation-integrity.md);
- [serving fallback](../operations/serving-fallback.md); and
- [limitations](../limitations.md).
