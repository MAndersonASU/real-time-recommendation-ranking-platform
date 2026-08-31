# Freshness reranking

MIND does not include article publication time. This policy therefore
uses a recency proxy and labels it as such.

Implementation: `src/recommender/reranking/freshness.py`.

## What “fresh” means here

For each article, the system records the earliest time it appeared as a
candidate in `train`. Age is the difference between that time and the
current impression time.

This is not publication age. It measures how recently the dataset first
showed the article.

## Measured support

| Observation | Value |
|---|---|
| Distinct validation candidates never seen in training | 53.9% |
| Candidate rows at most 12 hours old | 36.3% |
| Impressions with no candidate at most 12 hours old | 0.7% |

An unseen article has unknown age, represented by `NaN`. An older
implementation called it age zero and incorrectly favored it as
maximally fresh. `compute_age_days` now leaves it unknown, and an
unknown-age article cannot satisfy the freshness threshold.

The 12-hour threshold makes the quota available in almost every
impression while still selecting a limited part of the candidate pool.

## When the policy runs

MIND is a fixed 2019 dataset. Comparing its articles with today's wall
clock would not be meaningful.

`recommend()` applies the quota only when the caller supplies
`request_time`. Replay and evaluation provide that historical time. An
interactive request without it skips freshness reranking.

## Quota policy

Freshness runs after [diversity reranking](reranking-diversity.md):

1. Keep the slate when it already contains at least 2 articles whose
   observed age is at most 12 hours.
2. Otherwise, add the highest-scoring eligible fresh candidates.
3. Replace the lowest-scoring non-fresh items first.
4. Leave the slate unchanged when no eligible replacement exists.

A quota gives an explicit minimum when the candidate supply allows it.
A soft score boost would not guarantee how many fresh items reach the
final slate.

Freshness swaps do not reapply the diversity category cap. The two
policies remain separate and independently testable.

## Verification

`tests/test_freshness.py` checks:

- earliest-observed time;
- unknown age for unseen articles;
- no change when the quota is already met;
- highest-score replacement selection;
- replacement of the weakest non-fresh item;
- rejection of unknown-age replacements; and
- no forced change when fresh supply is absent.

The broader policy comparison and deployed-value decision are in the
[minimum-fresh experiment](min-fresh-experiment-protocol.md) and
[reranking evaluation](reranking-evaluation.md).
