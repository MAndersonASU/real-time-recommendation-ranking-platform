# Caching, With Explicit Freshness Rules

Names, for every cached thing in the serving path, exactly how stale it
is allowed to get and what makes it stop being valid — rather than
"loaded once, never checked" being the only rule by accident.
Implementation: `src/recommender/serving/cache.py`.

## What's cached, and its explicit rule

| Cached thing | Rule |
|---|---|
| Two-tower model weights, Faiss index, ranking model | Correct exactly as long as the on-disk artifact hasn't changed since load. Invalidated by a service restart after retraining — no code enforces this, it's a documented operational rule. |
| Durable per-user features (`DurableFeatureCache`) | Explicit 24-hour staleness **threshold**, checked via `is_stale()` against `data_as_of` — the newest event in the data, not the time the process loaded it. For this project the threshold is permanently exceeded: the MIND snapshot is from November 2019 and nothing refreshes it. `is_stale()` therefore returns `True` always, which is the Interpretation rather than a defect. Earlier wording here described a "refreshed daily" design intent and implied an automated refresh that does not exist. |
| Recent per-user features | **Not cached at all in this layer** — the online feature store's Redis store already is the fresh, live source of truth for these; caching them again here would just be a second, competing copy with its own staleness to track. |

## Why the cache doesn't refresh itself

`DurableFeatureCache.is_stale()` reports staleness; it never triggers a
refresh on its own. Recomputing durable features means re-reading a real
offline split and rebuilding the whole per-user dictionary — genuine
batch-shaped work, the kind of thing a live request path should never
be the one to trigger. `refresh()` exists as a separate, explicit call a
scheduled job or an operator makes, returning a new cache with a new
timestamp rather than mutating the old one in place, so a caller
already holding a reference to the previous cache keeps a consistent
snapshot instead of values shifting under it mid-read.

## Why this, not a request-level response cache

A cache that stored a full computed recommendation per user would need
an explicit invalidation rule tied to the online feature store's live recent-feature
writes — serving a cached response across a real click would directly
defeat the purpose of the streaming work and the online feature store. Given this
project's `recommend()` already runs in single-digit milliseconds
end to end (`docs/inference-path.md`), a response cache would trade a
small latency win for a real, hard-to-get-right freshness rule with
no measured need behind it — exactly the kind of complexity the
project's own no-added-tool-without-a-measured-requirement policy rules
out.
