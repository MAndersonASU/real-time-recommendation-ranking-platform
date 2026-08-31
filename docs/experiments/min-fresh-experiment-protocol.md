# Frozen protocol for the minimum-fresh quota

**Status: committed before the experiment ran.**

The selection rule below was fixed before results were viewed. If it
selected a value other than the deployed quota, the project had to
either adopt that value or record the deployed value as a policy
override.

## Why the experiment was needed

The deployed minimum-fresh quota is 2. An earlier 1,500-impression
comparison used predicted relevance. At budgets of 0.90, 0.95, and
0.99, its rule selected quotas 5, 5, and 3—not 2.

That evidence had three limits:

- it measured model scores rather than observed clicks;
- quota 2 and quota 3 differed by about 0.15% predicted relevance; and
- uncertainty from the sampled impressions was not quantified.

Choosing another budget after seeing that table could simply reproduce
a preferred answer.

## Frozen design

| Item | Decision |
|---|---|
| Population | Complete tuning fold carved from `train` |
| Fold seed | `20260823` |
| Validation use | None |
| Quotas | {0, 1, 2, 3, 5} |
| Baseline | Quota 0 |
| Primary measure | NDCG@10 |
| Guardrail | Hit rate@10 |
| Uncertainty | Paired bootstrap clustered by user |
| Relevance floor | 99% retention |
| Hit-rate floor | 95% retention |
| Selection | Largest quota clearing both one-sided 95% lower bounds |

Every quota is evaluated on exactly the same impressions. Pairing
measures within-impression differences. Clustering keeps all
impressions from one user together because those observations are not
independent.

Using the complete fold removes the extra variation caused by selecting
a smaller subset. Confidence bounds remain necessary because the fold
itself represents a wider user population.

## Why the 99% floor was chosen

The rule allows at most 1% relative NDCG loss against quota 0.

- A 99.9% floor was rejected because the existing score table already
  showed that it selected the deployed value 2.
- A 95% floor was rejected as too permissive for a system with
  end-to-end hit rate@10 of 0.0084.

These rejected alternatives were recorded before the run.

## Decision rule

Select the largest nonzero quota whose:

- one-sided 95% lower bound on NDCG@10 retention is at least 99%; and
- one-sided 95% lower bound gives hit-rate@10 retention ≥ 95%.

If no nonzero quota qualifies, the experiment does not support a
freshness quota. Retaining quota 2 would then be an explicit policy
override.

## Diagnostic values

The report also includes:

- mean predicted relevance;
- share of slates meeting the quota;
- mean fresh items per slate; and
- distinct categories after reranking.

These values explain the outcome but do not select the quota.

## Required report contents

The machine-readable report records:

- full-fold impression and user counts;
- quota-0 baseline values;
- every quota's results;
- paired confidence bounds;
- the frozen rule and selected quota;
- source commit; and
- artifact hashes.

This is a prospectively specified tuning-fold policy experiment. It is
not a final generalization estimate, and no untouched final split
remains.

## What the experiment cannot answer

Logged clicks show whether reranking would have retained articles that
were clicked in the recorded candidate list. They cannot reveal what a
person would have clicked after seeing a different live slate.

The experiment can bound offline relevance cost. It cannot measure the
long-term value of fresher recommendations. That would require a live
experiment outside this project's scope. See
[limitations](../limitations.md).
