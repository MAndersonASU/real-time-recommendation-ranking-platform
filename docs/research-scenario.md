# Research Scenario

**Project:** Real-Time Personalized Recommendation & Ranking Platform
**Research domain:** Personalized news/content recommendation with implicit user feedback.
**Dataset:** Microsoft News Dataset (MIND) — MIND-small for development; MIND-large only for justified, explicitly-scoped scale testing (the scale and performance work).

## Core problem

Given a user, their recent behavior, a set of candidate content items, and context,
retrieve a bounded candidate set and rank the most useful items under explicit
latency and system constraints.

## Core output

A ranked Top-K recommendation list, plus traceable model, feature, latency, and
evaluation evidence for every reported result.

## Research questions (frozen)

- **RQ1** — How much do learned embeddings and candidate retrieval improve
  recommendation quality over simple baselines?
- **RQ2** — How much does a dedicated ranking model improve quality over
  retrieval scores alone?
- **RQ3** — Can reranking improve diversity/freshness without unacceptable
  loss of relevance?
- **RQ4** — How do streaming user signals change online features and
  recommendation freshness?
- **RQ5** — What quality-versus-latency tradeoffs appear as candidate set
  size, index type, batching, and caching change?

RQ1 evaluates Recall of the retrieval stage's candidate set of size **N**;
RQ2 evaluates Recall/NDCG of the final served **Top-K** list. N and K are
tracked as separate parameters throughout and are never conflated, since
they answer different questions.

## User-event vocabulary

- **Impression** — one candidate list actually shown to a user in a single
  serving instance; contains both clicked and non-clicked items.
- **Click** — positive implicit feedback: the user selected an item from an
  impression.
- **Skip** — an item shown in an impression but not clicked; an implicit
  negative, not necessarily disinterest.
- **Session/history** — the sequence of a user's past impressions and clicks
  used as input context for personalization.

## Success metrics

Defined precisely alongside the baselines, once the evaluation contract is frozen; named
here only to fix scope: Recall@K, NDCG@K, MRR, hit rate, catalog coverage,
and diversity/freshness measures where supported by the data.

## Definition of "real-time" (scope boundary)

"Real-time" in this project means **replayed-stream processing** —
historical interactions replayed through Kafka in chronological order at
controlled speed, processed incrementally by a live consumer. It does
**not** mean live production traffic or real users. This distinction is
binding on every later document and must not be blurred in code, comments,
or the eventual research release.

## Prohibited claims

Unless independently measured and verified at the time of writing:

- No claim of internet-scale traffic, real users, or business impact.
- No claim of "production deployment" — only "production-grade"
  *engineering practices* (tested, containerized, monitored) demonstrated
  locally.
- No claim of a ranking improvement without stating that both compared
 systems used the identical frozen evaluation contract (the baselines).
- No treatment of replay-based evaluation as a real A/B test.

## Boundary: what this project does not do

- No Spark, Flink, Kubernetes, cloud hosting, distributed TorchRec, a
 feature store, or an LLM, unless a measured requirement in a future work
  justifies adding it.
- The optional explanation generation generative/RAG explanation layer explains an
  already-selected recommendation; it never participates in retrieval,
  ranking, or reranking decisions.

---

*Locked 2026-08-15. This document is the fixed reference point every later
component's evaluation is measured against; revising it after model results
exist would invalidate prior comparisons and must be treated as a new
locked version, not a silent edit.*
