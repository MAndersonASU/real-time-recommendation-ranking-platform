# Automating CI

Three jobs, running three genuinely different kinds of check.
Implementation: `.github/workflows/ci.yml`.

## Three tiers, not one

`lint-and-test`: static checks (`ruff`, `bandit`), a `docker compose
config` validation, and the full unit/integration test suite (including
real FastAPI `TestClient` requests against synthetic fixtures — no real
infrastructure, no licensed data) — installed via `pyproject.toml`'s own
flexible lower bounds. `locked-install-test`: the identical test suite,
installed instead from `requirements-lock.txt`'s exact pinned versions
— a separate install path specifically so a lock file that's drifted
out of sync with `pyproject.toml` (a real gap a follow-up review found:
a dependency added to the runtime dependency list was never re-frozen
into the lock) gets caught here, not discovered by a user doing a
from-scratch install months later. `integration-smoke-test`: starts the
real Kafka and Redis containers in the CI runner and runs two real,
bounded round-trips against them — `verify_connectivity.py` (produce
and consume a real message) and `verify_state_store.py` (write, read
back, and measure real latency against a real Redis).

## Why the full API service isn't smoke-tested here

The trained two-tower model, the Faiss index, and the ranking pipeline
all depend on the licensed MIND dataset (`docs/dataset-source.md`),
which this project has never redistributed and never will. Kafka and
Redis are open-source images with nothing licensed involved, so they
run for real in CI; the full containerized API from
`docs/containerization.md` genuinely cannot, without either
redistributing data this project isn't allowed to redistribute, or
training a fake model just to make a smoke test pass — real complexity
added to test something that wouldn't actually be testing the real
system. This is the same "synthetic in CI, real data verified
separately and documented" line this project has held since Phase 1;
this step doesn't cross it, it just adds a real check on the one side
of that line CI actually can reach.

## A real bug found while wiring this up

`verify_connectivity.py` used one fixed topic name and one fixed
consumer group across every call, and never committed its offset.
Running it three times in a row against the long-lived local broker
surfaced a real failure: with no committed offset, a fixed group id has
nothing to resume from and re-reads the topic's very first message
every time — stale, from whichever run produced it, not the one that
call just produced. Fixed by generating a fresh topic and consumer
group per call, the same pattern `verify_recovery.py` already used —
confirmed by running the fixed version three times in a row
successfully, the exact scenario that exposed the bug in the first
place.
