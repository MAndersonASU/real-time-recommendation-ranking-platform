# Minimum-fresh quota: prospectively specified tuning-fold policy experiment

**Status: frozen before the experiment was run.** This document is
committed ahead of the run, and the selection rule below is not to be
changed after seeing the output. If the rule selects a value other than
the deployed one, the choice is to accept it or to record the deployed
value as a deliberate override — not to adjust the rule.

That constraint is the entire point. The existing predicted-score table
already shows which budget would select which quota, so a budget chosen
after the fact would be indistinguishable from fitting the rule to a
preferred answer.

## Why this experiment exists

The deployed minimum-fresh quota is **2**. The earlier tuning comparison
ranked candidate quotas by *predicted relevance* on a single sampled
1,500-impression subset, and reported that none of the three budgets
tested (0.90, 0.95, 0.99) selected 2 — the rule picked 5, 5 and 3.

That is weaker evidence than it sounds:

- It measured **what the model predicts**, not what users did.
- The gap between quota 2 and quota 3 is roughly **0.15%** of predicted
  relevance — well inside the range where a single subsample could
  decide the answer.
- Sampling uncertainty was never quantified
  (`LIMIT-SAMPLING-UNCERTAINTY-44`).

## 1. Relevance-retention budget

**99% retention.** At most a 1% relative loss against quota 0.

Two rejected alternatives, recorded so the choice is auditable:

- **99.9% was rejected**, even though it is defensible on its own terms.
  The existing table already shows 99.9% selects quota 2 — the currently
  deployed value — so adopting it now would reasonably read as
  outcome-driven.
- **95% was rejected** as too permissive for a system whose measured
  end-to-end hit rate@10 is 0.0084. A recommender with little relevance
  to spare should not be authorised to spend 5% of it.

## 2. Evaluation population

**The complete tuning fold**, not several sampled seeds.

This removes subsampling variance *within* the fold entirely rather than
estimating it. Statistical uncertainty is still computed, because the
fold is itself a sample of a user population — eliminating subsampling
error does not make the result exact.

The tuning fold is carved from `train` by `split_train_for_tuning`
(seed `20260823`). `validation` is not touched.

## 3. Outcome measures

The decision is made on **held-out click behaviour**, not predicted
score.

| Role | Metric |
|---|---|
| **Primary** | NDCG@10 |
| **Guardrail** | hit rate@10 |
| Diagnostic only | mean predicted relevance |
| Diagnostic only | freshness compliance (share of slates meeting quota) |
| Diagnostic only | mean fresh items per slate |
| Diagnostic only | post-reranking distinct categories |

Diagnostics are reported and do **not** enter the selection rule. They
exist to explain a result, not to justify one.

## 4. Statistical rule

Quotas **{0, 1, 2, 3, 5}**, evaluated on **exactly the same
impressions**. Quota 0 is the baseline.

Uncertainty is estimated by **paired bootstrap clustered by user**, not
independent impression-level resampling. Impressions from one user are
not independent observations — the same person's habits drive all of
them — so impression-level bootstrapping would understate the interval.
Pairing matters for the same reason it does in the diagnostics: every
quota sees identical impressions, so the difference is measured within
impression rather than between samples.

Select the **largest** quota satisfying **both**:

- one-sided 95% lower confidence bound on **NDCG@10 retention ≥ 99%**
- one-sided 95% lower confidence bound on **hit-rate@10 retention ≥ 95%**

**If no nonzero quota passes, the evidence does not support a freshness
quota at all.** Keeping quota 2 in that case remains an explicit product
override, and must be described as one.

## 5. Reporting

Reported as a **prospectively specified tuning-fold policy experiment**.
It is not an untouched final evaluation, and no untouched final split
exists in this project (`LIMIT-NO-FINAL-SPLIT-35`).

The published report carries:

- full-fold denominators and user count
- the quota-0 baseline
- every quota's metrics
- paired differences with confidence intervals
- the selection rule, restated
- the selected result
- source commit and artifact hashes

## What this experiment cannot settle

It measures reranking against **logged** click behaviour on a fixed,
already-decided candidate set. It cannot observe what a user would have
clicked had they been shown a different slate, so it bounds how much
relevance a freshness quota costs — not what a fresher slate is worth to
a reader over time. That question needs a live experiment this project's
scope does not attempt (`docs/limitations.md`).
