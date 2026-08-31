# Research scenario

| Item | Scope |
|---|---|
| Project | Real-Time Personalized Recommendation & Ranking Platform |
| Domain | Personalized news recommendation from implicit feedback |
| Main dataset | MIND-small |
| Scale dataset | MIND-large, only for explicitly scoped performance work |

## Problem

Given a user, their behavior, a catalog or candidate list, and request
context, return a bounded Top-K recommendation list within stated
latency and system limits.

Every published result must also identify its model, features,
configuration, sampling, metric definition, and provenance.

## Research questions

These questions were frozen before the reported results:

1. **RQ1 — Retrieval:** How much do learned embeddings and candidate
   retrieval improve quality over simple baselines?
2. **RQ2 — Ranking:** How much does a ranking model improve quality over
   retrieval scores alone?
3. **RQ3 — Reranking:** Can diversity and freshness improve without an
   unacceptable relevance loss?
4. **RQ4 — Streaming:** How do recent events change online user
   features and recommendation freshness?
5. **RQ5 — Tradeoffs:** How do quality and latency change with retrieval
   depth, index type, batching, and caching?

RQ1 measures whether the clicked item appears in the retrieved
candidate set of size **N**. RQ2 measures the final served list of size
**K**. N and K are separate throughout the project.

## Event terms

| Term | Meaning |
|---|---|
| Impression | One candidate list shown to a user |
| Click | An item selected from an impression |
| Skip | A shown item that was not clicked; this is an implicit negative, not proof of disinterest |
| History | Earlier impressions and clicks used for personalization |

## Metrics in scope

- Recall@K
- NDCG@K
- MRR
- hit rate
- catalog coverage
- diversity and freshness measures supported by the data

Exact definitions and denominators belong to the
[evaluation protocol](experiments/evaluation-protocol.md) and the JSON
reports.

## Meaning of “real-time”

“Real-time” means historical events replayed through Kafka in
chronological order at a controlled rate and processed by a live
consumer.

It does not mean production traffic or live users.

## Claims this project does not make

- internet-scale traffic;
- real-user or business impact;
- a production deployment;
- a ranking gain based on different evaluation contracts;
- replay as a substitute for a live A/B test.

The project does demonstrate local engineering practices such as tests,
containers, monitoring, recovery checks, and versioned artifacts.

## Technology boundary

Spark, Flink, Kubernetes, cloud hosting, distributed TorchRec, and a
separate feature store are outside scope because no measurement showed
they were required.

The optional local generative component can rewrite a grounded
explanation after recommendation selection. It cannot affect retrieval,
ranking, or reranking.

---

**Scope locked on 2026-08-15.** This plain-language revision changes
presentation only. It does not change the questions, metrics, dataset,
or claim boundaries. Any future scope change requires a new dated
contract rather than a silent edit.
