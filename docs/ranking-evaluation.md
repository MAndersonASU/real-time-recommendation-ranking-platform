# Retrieval-Only vs Ranked

The comparison this phase was built toward: on the exact same candidates —
the frozen `validation` split, MIND's own per-impression candidate list,
K=10 (`docs/evaluation-protocol.md`) — does the trained ranking model
(`docs/ranking-model.md`) order them better than the two-tower model's own
retrieval score used alone? Implementation:
`src/recommender/evaluation/evaluate_ranking.py`.

Both orderings score identical rows; only the sort key differs
(`retrieval_score` alone versus the ranking model's predicted click
probability), so any difference in the result can only come from the four
features the ranking model has beyond a raw retrieval score — category
match, content similarity, history length, hour of day — not from a
different candidate set or protocol.

## Real result

| Metric | Retrieval score only | Ranked |
|---|---|---|
| Hit rate@10 | 0.6689 | 0.6828 |
| Recall@10 | 0.5801 | 0.5975 |
| NDCG@10 | 0.3518 | 0.3671 |
| MRR | 0.3084 | 0.3347 |
| Catalog coverage@10 | 0.0698 | 0.0712 |

Evaluated on all 30,270 validation impressions. **The ranking model wins on
every metric, consistently, not on a mixed or ambiguous set of numbers.**
That is a direct, clean answer to RQ2 for this implementation: a dedicated
ranking model does improve ordering quality over the retrieval score
alone, given the same candidates.

## In context: every model measured so far

| Metric | Popularity | Content similarity | Collaborative | Retrieval score only | Ranked |
|---|---|---|---|---|---|
| Hit rate@10 | 0.5697 | 0.6557 | 0.5709 | 0.6689 | **0.6828** |
| Recall@10 | 0.5034 | 0.5743 | 0.5046 | 0.5801 | **0.5975** |
| NDCG@10 | 0.2830 | 0.3526 | 0.2847 | 0.3518 | **0.3671** |
| MRR | 0.2484 | 0.3236 | 0.2509 | 0.3084 | **0.3347** |
| Catalog coverage@10 | 0.0370 | 0.0722 | 0.0389 | 0.0698 | 0.0712 |

The ranked model beats every baseline in `docs/baselines.md` on every
metric except catalog coverage, where it's within rounding of the
content-similarity baseline's already-strongest result. This is the
strongest result on record across both phases, and it did not require
abandoning anything already built — it's a five-feature linear model
sitting on top of work from three separate phases (a popularity count from
Phase 2, a TF-IDF profile from Phase 2, a trained embedding score from
Phase 3).

## One more honest observation, not a new mystery

`retrieval_score` alone performs respectably here (0.6689 hit rate) —
noticeably better than it did in Phase 3's own full-catalog retrieval
evaluation (0.0044 hit rate at N=100, `docs/retrieval-evaluation.md`). That
is not a contradiction; it's exactly what the tied-vector limitation
already found in Phase 3 (`docs/faiss-index.md`) predicts. Searching the
full 51,282-item catalog, that limitation is severe — the model can only
identify a category cluster, then has no way to pick the right item among
however many share that cluster's identical vector. Restricted instead to
one impression's roughly 37 candidates (this phase's evaluation, by the
disclosed design choice in `docs/ranking-features.md`), the same coarse
category signal has far fewer competing items to distinguish between, so
it does meaningfully better — still a coarse signal, just operating over a
much smaller, easier disambiguation problem. Both results are correct
readings of the same underlying model; they are not directly comparable to
each other because they answer different questions over different
candidate pools.

## Phase 4 close

RQ2 — how much does a dedicated ranking model improve quality over
retrieval scores alone — has a clear, positive, quantified answer for this
implementation: yes, consistently, across every ranking metric measured,
using features that stayed genuinely available at inference time and
never leaked future information (`docs/ranking-features.md`). Every result
along the way was checked before being trusted rather than assumed: real
row-count and spot-check verification of the training data
(`docs/ranking-dataset.md`), a real generalization-gap diagnosis that
found and removed a harmful feature before it could distort the model
(`docs/ranking-model.md`), and a real calibration check confirming
predicted probabilities are honest, not just well-ordered
(`docs/ranking-calibration.md`).
