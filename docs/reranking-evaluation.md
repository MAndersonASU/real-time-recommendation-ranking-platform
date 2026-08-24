# Reranking Tradeoffs

RQ3's exact question — can reranking improve diversity and freshness
without unacceptable loss of relevance — measured directly: the plain
ranking-model slate (`docs/ranking-model.md`) against the full reranking
pipeline (diversity cap, then freshness quota:
`docs/reranking-diversity.md`, `docs/reranking-freshness.md`), same 30,270
validation impressions, same K=10, same candidates and scores throughout.
Implementation: `src/recommender/evaluation/evaluate_reranking.py`.

One methodological note, necessary and deliberate, not an inconsistency:
MRR here is the rank of a click *within the 10-item slate actually
produced*, not across the full candidate list the way earlier evaluations
computed it — the reranked policy only ever returns 10 items, so there's
no larger ordering to fall back to for a fair comparison. Recall and NDCG
still use the true total click count from the full candidate set (the
same correction built for retrieval's own top-N evaluation,
`docs/retrieval-evaluation.md`), not whatever's visible in the 10-item
slate alone — a real bug caught before trusting the first run of this
evaluation, see below.

## Real result

| Metric | Ranked only | Reranked | Change |
|---|---|---|---|
| Hit rate@10 | 0.6828 | 0.6675 | −2.2% |
| Recall@10 | 0.5975 | 0.5851 | −2.1% |
| NDCG@10 | 0.3671 | 0.3610 | −1.7% |
| MRR (slate-scoped) | 0.3188 | 0.3169 | −0.6% |
| Mean distinct categories | 4.50 | 5.33 | +18.3% |
| Mean max-category count | 4.25 | 2.82 | −33.5% |
| Mean fresh fraction | 0.442 | 0.440 | ~unchanged |
| Slates below the fresh quota | 13.3% | 4.8% | −64% relative |
| Catalog coverage@10 | 0.0712 | 0.0695 | −2.3% |

## Reading these numbers honestly

Relevance loss is real but small — every relevance metric dropped, none
by more than about 2%. Diversity improved substantially: the average
slate's dominant category shrank from 4.25 items to 2.82, and picked up
nearly a full additional distinct category on average.

The freshness population mean barely moving is not a failure — it's the
expected shape of a floor, not a boost. Most slates already had 2+ fresh
items before any policy touched them, so an average dominated by
already-compliant slates was never going to shift much. The metric that
actually shows the quota's effect is the fraction of slates that failed to
clear the floor at all: 13.3% down to 4.8%, a real, nearly two-thirds
relative reduction in how often a user would see an entirely stale slate.

Catalog coverage moved the wrong way, stated plainly rather than glossed
over: the diversity policy only ever reshuffles candidates *within* one
impression's own already-narrow pool — it has no mechanism to introduce
catalog items that weren't already candidates for that user. Making one
slate more varied internally is a different property from making the
whole system recommend more distinct items across everyone, and this
result shows those two things don't automatically move together — a real,
disclosed limitation of a per-impression policy, not a system-wide fix.

## A real bug caught before trusting the first run

The first run of this evaluation reported recall_at_k exactly equal to
hit_rate_at_k for both policies — a red flag, not a coincidence worth
ignoring. Traced to the same category of bug already diagnosed once for
retrieval's own evaluation (`docs/retrieval-evaluation.md`):
`recall_at_k`/`ndcg_at_k` infer the true relevant count
from whatever array they're handed, correct only when that array is the
complete candidate set. Both the ranked-only and reranked slates here are
only 10-item slices of a larger ~37-item candidate pool, so passing the
slice directly collapsed recall into hit rate and understated what a
perfect slate could have achieved. Fixed by reusing
`recall_at_n_known_total`/`ndcg_at_n_known_total`
(`src/recommender/evaluation/retrieval_metrics.py`), passing the true click
count from the full candidate group rather than inferring it from the
10-item slate — confirmed with a targeted test asserting the corrected
value (0.5) differs from what the naive slice-only calculation would have
given (1.0) for a click that falls outside the slate.

## Honest answer to RQ3

For this implementation: yes, on diversity and on the freshness floor, at
a relevance cost under 2.2% on every metric measured — with one genuine,
disclosed caveat, that catalog-wide coverage moved slightly the wrong
direction, a real limitation of a per-impression policy rather than a
system-wide one. Whether that specific tradeoff is "acceptable" is
ultimately a product decision this step can quantify but not resolve on
its own.
