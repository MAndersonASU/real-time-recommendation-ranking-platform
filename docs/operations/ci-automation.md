# Automating CI

Four jobs, running four genuinely different kinds of check.
Implementation: `.github/workflows/ci.yml`.

## Four jobs, not one

**`lint-and-test`** — static checks (`ruff`, `bandit`), a
`docker compose config` validation, and the full test suite behind a
coverage floor, installed via `pyproject.toml`'s own flexible lower
bounds. Real FastAPI `TestClient` requests against synthetic fixtures;
no infrastructure, no licensed data.

**`locked-install-test`** — two separate, hash-verified installs, not
one. `requirements-lock.txt` (the runtime lock this project's container
image ships) installs alone into its own virtualenv (`/tmp/runtime-env`)
and is checked only for whether the serving path still imports from it
— asserting the narrow property that matters for a runtime image.
Separately, in the job's own default environment,
`requirements-dev-lock.txt` installs and the full test suite runs
against it (`pytest -q`), and `pip-audit` audits that same
development-lock environment afterward, not the runtime-only
virtualenv. A lock file drifted out of sync with `pyproject.toml` is
invisible to the flexible install above, which always resolves *some*
working set; hash verification additionally means a package republished
under a pinned version is rejected rather than silently installed.

**`api-container-test`** — builds and runs the real containerized API,
waits on the container's own health check, asserts it runs as a
non-root user, and makes real HTTP requests against it: `/health`,
`/ready`, a `/recommend` call checked for both a contract-valid body and
an `X-Request-ID` header, a malformed `/demo` request checked for a
clean 422 rather than a 500, and `/metrics` checked for the derived
serving version.

**`integration-smoke-test`** — starts the real Kafka and Redis
containers and runs five checks against them: a Kafka produce/consume
round trip (`verify_connectivity.py`); a Redis round trip and latency
measurement (`verify_state_store.py`); the atomic claim-and-apply Lua
script against real Redis, not the in-memory stand-in every other test
of it uses (`verify_lua_idempotency.py`); the same script under eight
concurrent writers, which the sequential check above cannot exercise
(`verify_lua_concurrency.py`); and that an acknowledged write survives
a `SIGKILL`, not a graceful stop, which would pass even with AOF
disabled (`verify_aof_recovery.py`).

## How the API container is testable here at all

The trained two-tower model, the Faiss index, and the ranking pipeline
all derive from the licensed MIND dataset (`docs/dataset-source.md`),
which this project has never redistributed. For a long time that meant
the containerized API simply could not run in CI — the image would
start, fail to load its artifacts, and exit — so the container was
verified only locally.

`recommender.data.synthetic` removes that blocker without crossing the
licensing line: it generates a seeded, entirely synthetic catalog,
splits, and trained models, written to the same paths the real artifacts
occupy. The serving code needs no CI-only branch, and nothing licensed
is involved.

The models are trained through the real training code paths rather than
hand-assembled, deliberately: an artifact built some other way could
load cleanly while the real training path was broken, which is exactly
the failure this is meant to catch.

What this does and does not prove is worth stating plainly. It proves
wiring: the image builds, starts unprivileged, loads its models, passes
its health check, and returns contract-valid responses. It proves
nothing about recommendation quality — the synthetic model's scores are
meaningless, and every quality number this project publishes still comes
from local runs against the real licensed data
(`docs/experiments/serving-path-end-to-end-evaluation.md`).

## A bug found while wiring this up

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
