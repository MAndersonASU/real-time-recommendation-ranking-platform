# Replay-Based Evaluation

Runs the real, full serving pipeline — retrieval, ranking, reranking,
all of it — against real historical impressions from the reserved
`replay` split, checking whether the live system's slate would have
contained what the user actually clicked. Implementation:
`src/recommender/tracking/replay_evaluation.py`.

## A simulation, not a live A/B test

Every prior evaluation in this project (baselines, ranking, reranking) scored features
computed once, offline, from each impression's own recorded history.
This check is different: it calls the actual `recommend()` pipeline
(`docs/operations/inference-path.md`), which pulls online features from whatever
state currently exists — the durable cache built from the `validation`
split, and Redis's current contents — not the exact point-in-time state
a truly live system would have had at each impression's real historical
moment. That gap is real, and it's the whole reason this is called a
simulation rather than a live test: a real online A/B test observes a
system that has actually been receiving live traffic; this observes the
same code, running against whatever offline snapshot the feature stores
happen to hold right now.

## A real, chased-down zero

The first run came back with a **0.0 hit rate@10 over 500 sampled
impressions with a real click** — worth investigating, not reporting
blindly. The cause traces to two already-documented facts about this
project converging on this one sample, not a new bug:

- **92.4% of the sampled replay users never appear in the `validation`
  split** (38 of 499), so the durable feature cache — built from
  `validation` — falls back to neutral defaults for almost everyone.
  **0% had a live Redis record at all** (checked directly), so recent
  features fall back too. A fully cold user's history mask is all
 zeros, which the two-tower model's mean-pooling (`docs/experiments/retrieval-model.md`) reduces to the same zero vector for every one of them —
  every cold user gets an identical, entirely generic retrieval result.
- Even the 38 users who *did* have durable features scored **0 of 38**
  as well. A durable-only signal is just a dominant category match, and
  the item tower's own vector collapse (`docs/archive/faiss-index.md`) had at
  the time reduced the whole ~51,000-item catalog to only 284 distinct
  vectors — roughly 180 items
  tied within a category. Landing on the one specific article a real
  user clicked, among that many ties, remains close to chance even with
  partial personalization.

## Why this matters

This is a genuine, mechanically-explained illustration of the
offline-to-online gap documented formally in `docs/limitations.md` — not foreshadowing
invented for this write-up, but the actual first measurement of
it. A replay-based evaluation is only as informative as the online
feature state it runs against; running it against users this
deployment has simply never seen live traffic for measures cold-start
behavior, correctly, and nothing else. The right fix isn't in this
analysis: it would be evaluating against `replay` users who *do* have prior
live interaction history recorded in Redis, which requires actually
running the streaming replay (the streaming pipeline) against a matching population
first — a real, disclosed scoping boundary of what this check alone can
show.
