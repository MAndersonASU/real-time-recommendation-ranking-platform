# Uncertainty and Limits

Every real limitation found across this project, gathered into one
place rather than left scattered across the individual docs pages that
first found each one. Nothing here is a new claim — every number and
finding links back to the step that actually measured it.

## Sparse-user behavior

A given window's users mostly interact once or twice, not repeatedly.
A direct measurement of the training window found a median of 1–2
interactions per user, with a small number of much more active users
(max 18–62) pulling the mean up. Most of what any model in this project
learns about "typical" user behavior is shaped by that thin, one- or
two-interaction majority — there is very little historical signal to
personalize against for most users in any single window, which is the
underlying reason Phase 7's whole feature split (durable vs. recent)
and Phase 7.5's cold-start fallbacks exist at all, not an edge case
bolted on afterward.

## Cold start, measured directly, not assumed

Phase 7.5 built explicit fallback behavior for users with no known
features. Replay-based evaluation (`docs/replay-
evaluation.md`) measured how common that actually is in practice, using
this project's own real feature stores: of 499 sampled `replay`-split
users, **92.4% never appeared in the `validation` split** the durable
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
  uncapped. The live path (`docs/inference-path.md`) only ever has
  access to a user's last 20 recent clicks, the cap Phase 7's Redis
  store chose for latency reasons. `user_history_length` at serving
  time deliberately reads from the durable `lifetime_click_count` field
  instead of the capped recent list specifically to avoid a second,
  silent mismatch on top of this one.
- **Feature staleness.** Durable features are refreshed on an explicit
  24-hour cadence (`docs/serving-cache.md`), not continuously — a live
  request can be scored against a durable snapshot that is, by design,
  up to a day old.

Replay-based evaluation (`docs/replay-evaluation.md`) is the first place
these two gaps were actually measured together on real data, rather than
reasoned about individually.

## Selection bias in the underlying data

MIND's impression logs are themselves the output of Microsoft's own,
different, already-deployed recommender — a fact never stated plainly
until now, though every evaluation in this project has depended on it.
A user could only ever click an article that some earlier system chose
to show them. Every metric in this project (`docs/evaluation-
protocol.md` onward) measures agreement with *that* system's own past
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
and NDCG number in every phase compares this project's ranking against
a fixed, already-decided candidate set and a fixed, already-observed
click — a real, permanent ceiling on what offline evaluation alone can
prove. Confirming that this project's system would perform differently
against genuinely different candidate sets — the actual question a real
production deployment cares about — requires a live experiment (a real
A/B test) that this project's frozen research scope (`docs/research-
scenario.md`) explicitly does not attempt, and the replay-based
evaluation (`docs/replay-evaluation.md`) was equally
explicit about not pretending to be one.
