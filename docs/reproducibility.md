# Reproducibility Verification

The README's "Getting started" instructions are a claim until someone
actually starts from nothing and checks them. This document records a
real, independent verification: a genuine second `git clone` into an
empty directory, a brand-new virtual environment, a from-scratch
dependency install, the full test suite, and the real containerized
service — not a re-run inside the already-working development copy.

## What was actually done

1. `git clone` the public repository into a directory that had never
   held any part of this project before.
2. A brand-new Python virtual environment, dependencies installed with
   `pip install -e ".[dev]"` and no prior pip cache assumptions beyond
   the standard package index.
3. `pytest -q` and `ruff check .` — both run before anything else
   touched the real dataset.
4. The already-produced offline artifacts (trained model, Faiss
   indexes, splits, reports — never the raw licensed dataset itself)
   copied into the fresh clone's `data/` directory, then
   `docker compose up -d --build` from that same fresh clone.
5. Real requests against the freshly built container:
   `GET /ready` and `GET /demo/{user_id}`.

## A real reproducibility bug this check actually found

The first attempt at step 2 failed outright:
`ERROR: Package 'recommender' requires a different Python: 3.14.2 not
in '<3.12,>=3.11'`. The README's "Getting started" section said
`python -m venv .venv` with no mention of which Python version that
command needs to resolve to — on this machine, plain `python` resolves
to 3.14, not the pinned 3.11 the project actually requires (chosen
originally because PyTorch, Faiss, and this project's other heavier
dependencies typically lag behind the newest CPython release). This
was a real, silent assumption baked into every earlier setup in this
project (the working development environment already had a 3.11 venv
from Phase 0, so the gap was never surfaced until a genuinely fresh
environment was checked). Fixed by adding the explicit version
requirement to the README's quickstart.

## Real result: 215/215 tests pass, zero licensed data required

```
215 passed in 29.91s
All checks passed! (ruff)
```

Every dependency `pyproject.toml` declares was sufficient on its own —
nothing "worked" only because it happened to already be present from
an earlier install. No file under `data/raw/` or any real MIND content
was needed for this to pass, confirming the CI-mirroring claim in
`docs/ci-automation.md` holds for a genuinely fresh environment too,
not only inside GitHub's own runners.

## Real result: the containerized services, from the fresh clone

The original repository's running containers were stopped first (to
free the fixed host ports and container names both copies use), then
`docker compose up -d --build` was run directly from the fresh clone.
Real result: `recommender-kafka`, `recommender-redis`, and
`recommender-api` all reported healthy; `GET /ready` returned
`{"ready": true, ...}`; `GET /demo/U73700` returned the same real
ranked slate and explanations as the original build (per-stage latency
within normal machine-timing variance of the numbers already recorded
in `docs/professional-demonstration.md`). The original repository's
own containers were rebuilt and restored afterward.

## Exact dependency versions (requirements-lock.txt)

`pyproject.toml` declares only lower bounds (`pandas>=2.2`, and so on)
with no upper bound and no lock file at all, so a fresh install can
silently resolve to a newer, untested version of any dependency -- the
exact-version story above is about *this project's own code*, not about
pinning what it depends on.

`requirements-lock.txt` is the exact, fully-resolved set of every
runtime and dev-tool dependency version the full test suite has
actually passed against -- generated via `pip freeze` from a real
working environment, not typed by hand. A first version of this file
omitted `skops` (added to `pyproject.toml`'s runtime dependencies but
never re-frozen), which broke a from-scratch install with test-collection
errors -- found by a follow-up review and fixed by regenerating the
lock from an environment that actually has every declared dependency
installed.

Verified for real, from scratch: a genuinely fresh virtual environment,
`pip install -r requirements-lock.txt`, `pip install --no-deps -e .`,
then the complete test suite -- all pinned packages installed cleanly
and every test passed. `pyproject.toml`'s loose lower bounds remain the
default install path (what the fresh-clone check above actually
exercised); this file is the additional, exact-reproduction option for
anyone who wants the precise versions already known to work, not a
replacement for the flexible path. CI runs both: a lower-bound install
job (matching the flexible path) and a locked install job (matching
this file) — see `.github/workflows/ci.yml`.

## The one honest limitation this doesn't remove

The licensed MIND dataset itself was not re-downloaded for this
check — the already-produced, already-verified offline artifacts were
reused directly, matching the project's own no-redistribution policy
(`docs/data-card.md`). A genuinely first-time user still needs to
obtain the dataset from its canonical source (`docs/dataset-source.md`)
and run the offline pipeline themselves before the live services will
serve real personalized recommendations; the test suite alone requires
nothing beyond a clean clone.
