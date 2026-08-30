# Uncertainty and Limits

The limitations of the evaluation itself: what the numbers this project
publishes can and cannot show, gathered into one place rather than left
scattered across the individual docs pages that first found each one.
Nothing here is a new claim — every number and finding links back to
the operation that measured it.

This page is not the complete limitations register. Engineering-level
limitations -- properties of the implementation that no fix is
currently planned for, as distinct from a finding that was fixed -- are
tracked in `docs/engineering-review-register.md`'s own **Accepted
limitations** table (`LIMIT-*`/`HIST-*`, twelve entries: unaudited
CPU-only torch, no untouched final split, low absolute recommendation
quality, global cold-start popularity, recency analysis confounded by
user composition, judgment-based tuning parameters, public CI's
licensed-data ceiling, the claim-retention idempotency window, lexical-
only explanation validation, an earlier CI-status overclaim, unquantified
sampling error, and the `hour_of_day` offline/online timezone mismatch).
Those are separate again from the **2 findings** among the register's 23
primary findings that carry the status `accepted limitation` -- a
finding the project chose not to fix, not a documented characteristic
like the twelve above. Read the register directly rather than inferring
a limitation count from this page alone.

## Sparse-user behavior

A given window's users mostly interact once or twice, not repeatedly.
A direct measurement of the training window found a median of 1–2
interactions per user, with a small number of much more active users
(max 18–62) pulling the mean up. Most of what any model in this project
learns about "typical" user behavior is shaped by that thin, one- or
two-interaction majority — there is very little historical signal to
personalize against for most users in any single window, which is the
underlying reason the online feature store's whole feature split (durable vs. recent)
and its cold-start fallbacks exist at all, not an edge case
bolted on afterward.

## Cold start, measured directly, not assumed

The online feature store built explicit fallback behavior for users with no known
features. Replay-based evaluation (`docs/experiments/replay-evaluation.md`) measured how common that actually is in practice, using
this project's own real feature stores: of a seeded sample of 497 distinct
`replay`-split users, **93.6% never appeared in the `validation` split** the durable
cache is built from, and **0% had any live Redis record at all** at the
time of that measurement. Cold start here isn't a rare corner case to
handle defensively — for a system whose online feature stores haven't
been continuously fed by real traffic, it is close to the default case.

## Offline-to-online gaps

Two distinct, disclosed gaps exist between how a feature is computed
during offline training and how the same feature is computed for a live
request:

- **History length.** Offline training's content-similarity profile
  (`ranking/features.py`) pools a user's entire recorded history,
  uncapped. The live path (`docs/operations/inference-path.md`) only ever has
 access to a user's last 20 recent clicks, the cap the online feature store's Redis
  store chose for latency reasons. `user_history_length` at serving
  time deliberately reads from the durable `lifetime_click_count` field
  instead of the capped recent list specifically to avoid a second,
  silent mismatch on top of this one.
- **Feature staleness.** Durable features are **never refreshed**. They
  are a frozen historical snapshot of a 2019 dataset
  (`docs/operations/serving-cache.md`), and restarting the service reloads the same
  data rather than making it newer. The 24-hour value is a staleness
  *threshold* that this snapshot exceeds permanently and by design, not
  a refresh cadence. An earlier version of this line described it as a
  cadence, which implied an automated refresh that does not exist.
  `/ready` reports the real age and states the policy.

Replay-based evaluation (`docs/experiments/replay-evaluation.md`) is the first place
these two gaps were measured together on real data, rather than
reasoned about individually.

## Selection bias in the underlying data

MIND's impression logs are themselves the output of Microsoft's own,
different, already-deployed recommender — a fact never stated plainly
until now, though every evaluation in this project has depended on it.
A user could only ever click an article that some earlier system chose
to show them. Every metric in this project (`docs/experiments/evaluation-protocol.md` onward) measures agreement with *that* system's own past
selections, not true, unconditional relevance to the user. An article
this project's model would have correctly recommended, but the original
system never displayed, has no way to appear as a "hit" in any of these
numbers, however good the recommendation actually would have been —
not because the metric is wrong, but because the logged data structurally
cannot answer that question.

## Unavailable counterfactual outcomes

The direct consequence of the point above: this project has never once
observed what a user would have clicked *if shown something different*
from what the logged system actually displayed. Every hit rate, recall,
and NDCG number in every component compares this project's ranking against
a fixed, already-decided candidate set and a fixed, already-observed
click — a real, permanent ceiling on what offline evaluation alone can
prove. Confirming that this project's system would perform differently
against genuinely different candidate sets — the actual question a real
production deployment cares about — requires a live experiment (a real
A/B test) that this project's frozen research scope (`docs/research-scenario.md`) explicitly does not attempt, and the replay-based
evaluation (`docs/experiments/replay-evaluation.md`) was equally
explicit about not pretending to be one.

## New articles cannot be served without a refit

The persisted content artifact is a matrix covering the catalog it was
fitted on. The fitted TF-IDF vocabulary and SVD basis that produced it
are not persisted, so there is no way to project a genuinely new article
into the same coordinate system at serving time. A new article can only
enter the content-aware retrieval path by refitting the transformation
and retraining the item tower against it.

This is a scope boundary rather than an oversight: the platform is
evaluated against a frozen MIND snapshot and has no online
item-onboarding flow, so persisting the transformers would add an
artifact that nothing in this system exercises. It is stated here
because "content-aware retrieval" otherwise implies an ability this
does not have (ARTIFACT-TRANSFORMERS-07 in `docs/engineering-review-register.md`).

## Retrieval queries ignored durable history (resolved)

**Status: resolved.** SERVING-DURABLE-HISTORY-69 in
`docs/engineering-review-register.md` fixed this; the description below
is preserved as the historical account of the gap, not the current
behaviour.

`recommend()` built its two-tower query vector from the user's recent
in-session clicks held in Redis, and from nothing else. A returning user
with a long durable click history but no activity in the current window
therefore produced an empty query, and retrieval proceeded as if the user
were a cold-start user — they received the global popularity-shaped slate
while their own history sat unused in the durable feature store.

This was found by running the API against real users rather than by
reading the code, and it was a genuine gap between what the offline
evaluation measured and what the live path did: the end-to-end
evaluation seeds its isolated store from each impression's own
point-in-time `history` field, so it exercised a query the live service
would not have constructed for the same user. The reported
`recent_feature_coverage` of 97.6% reflected that seeding, not live
behaviour.

**Fix.** `recommender.serving.pipeline.select_retrieval_history` now
builds the two-tower query, Faiss retrieval, and content-similarity
profile from the user's bounded durable history
(`DurableUserFeatures.history_item_ids`) whenever Redis has no usable
recent click history, rather than leaving the query empty. Recent
history still takes precedence when it exists; durable and recent are
never merged. The response's `retrieval_history_source` field reports
which of the three (`recent` / `durable` / `global_popularity`)
actually drove a given request, so this distinction is now observable
per-response rather than only inferable from reading the code.

**Evidence.** A dedicated evaluation
(`docs/experiments/durable-history-fallback.md`,
`reports/durable-history-fallback.json`) measures a cohort of real
users who have a usable point-in-time durable history against a
genuinely empty, isolated Redis store — the exact condition this
limitation described — and reports post-fix catalog coverage, served-
slate diversity, and ranking-quality metrics. This is not a paired
before/after comparison: no matching pre-fix baseline was measured at
this scale, only established directly by reproduction and by reading
the pre-fix code, both recorded in that document alongside the post-fix
numbers. It does not use the 31 interactive requests that first
reproduced this defect as a quality estimate; those are reproduction
evidence, not a representative sample.
