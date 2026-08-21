# Low-Latency State Storage

Gives recent user features (`docs/online-features.md`) a real, external,
low-latency home instead of only living inside one Python process's
memory. Implementation: `src/recommender/features/state_store.py`.

## Redis, not Feast

The recent-feature side of Phase 7 needs one thing: a store that can be
written to and read from in well under a millisecond, with keys that
expire on their own. Feast is a full feature-store framework — it manages
feature definitions, materialization jobs, and point-in-time joins as its
own layer, typically sitting on top of a store like Redis anyway. That
machinery earns its cost once a project has many features, many models,
and multiple serving surfaces that all need a shared, versioned feature
definition layer. This project has two recent features (`docs/online-
features.md`) and one consumer of them, so Feast would add an entire
framework's worth of concepts to solve a coordination problem that
doesn't exist here. Redis plus two plain functions does the actual job.

## What's stored

`save_recent_features` writes a user's full `RecentUserFeatures` record as
a single JSON string under `recent_features:<user_id>`, with a 24-hour
expiry — a user who stops sending events should eventually fall out of
the store rather than being served forever from a stale snapshot.
`load_recent_features` returns `None` for a user with no key, whether
because they've never sent an event or their key expired; callers treat
that `None` as the cold-start case handled in Step 7.5, not an error.

## Verified against a real container

`verify_state_store.py` writes one real record to the actual Redis
container (`docker-compose.yml`), reads it back, and confirms every field
matches — not a mock. It also measures real read latency over 200 lookups
against the running container: **0.29 ms p50, 1.12 ms p99**. This is the
number behind the phase's "low-latency feature path" exit criterion.
