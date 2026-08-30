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

A seeded uniform sample of 500 impressions from the whole `replay`
split (`recommender.evaluation.sampling`) — not the first 500 rows in
the split's own on-disk order, as an earlier version of this check
took — still comes back with a **0.0 hit rate@10 over 500 sampled
impressions, all 500 with a real click**. This is not an artifact of
the earlier, biased sampling: the same zero persists under a genuinely
representative draw. The cause traces to two already-documented facts
about this project converging on this one sample, not a new bug:

- **93.6% of the sampled replay users never appear in the `validation`
  split** (465 of 497 distinct sampled users), so the durable feature
  cache — built from `validation` — falls back to neutral defaults for
  almost everyone. **0% had a live Redis record at all** (checked
  directly, `describe_online_feature_coverage`), so recent features
  fall back too. A user with neither a durable nor a recent signal has
  a fully empty, zero-norm history, which current retrieval detects and
  routes to the global-popularity candidate path instead of a Faiss
  search (`docs/operations/serving-fallback.md`) — every such cold user receives the
  same catalog-wide popularity ranking as their candidate pool,
  regardless of who they are. 468 of these 500 impressions fall into
  this case (`retrieval_history_source: "global_popularity"`, checked
  directly against this exact sample).
- The other 32 impressions -- the users who *did* have durable
  features -- scored **0 hits** as well, so the aggregate 0.0 hit rate
  over all 500 impressions makes that arithmetically certain, not
  merely observed. Since SERVING-DURABLE-HISTORY-69's fix, these 32
  genuinely retrieve on the user's own durable history
  (`retrieval_history_source: "durable"`, checked directly against this
  exact sample -- real Faiss search on a real embedding, not a ranking-
  side category match layered over the same popularity pool everyone
  else gets, which is what this same 32-user subset got before the
  fix). Landing on the one specific article a real user clicked remains
  close to chance even with that real personalization, at this sample
  size: 32 real attempts is not enough to expect even one hit at this
  project's measured hit-rate order of magnitude (roughly 1% elsewhere
  in this project) -- a genuine improvement to *what* is retrieved for
  these users would not necessarily be visible as a nonzero hit count
  in a sample this small, and this replay draw does not claim otherwise.

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
running the streaming pipeline against a matching population
first — a real, disclosed scoping boundary of what this check alone can
show.
