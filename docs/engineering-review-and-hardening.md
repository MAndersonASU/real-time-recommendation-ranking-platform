# Engineering Review and Hardening

A maintainer-led engineering review of this project's serving path,
evaluation methodology, reproducibility, and privacy handling. All
changes and every reported test result below were reviewed and
executed by the maintainer — this document summarizes what changed and
why; it does not claim third-party certification or an external audit.

**Date**: 2026-08-24. **Reviewed against**: the `main` branch, starting
from commit `cd8a4d776ad81b47313e2761e2ba9c3918293c26`.

## Scope

Four areas, reviewed together because a change in one routinely implied
a change in another:

- **Serving-path correctness** — exception handling at the actual
  dependency boundaries (Redis, the two-tower model, the Faiss index),
  request-ID and error-log preservation on unhandled exceptions,
  timezone handling, and the faithfulness of generated explanation
  text.
- **Evaluation methodology** — whether a held-out split used for a
  feature/hyperparameter decision really was held out, and whether the
  serving-path evaluation script reconstructs each historical request's
  state as it actually existed at that point in time, rather than
  reusing state built from a later point.
- **Reproducibility** — whether the dependency lock file installs
  cleanly and completely in a fresh environment, and whether CI runs
  what the documentation says it runs.
- **Privacy and operational hardening** — raw-identifier leakage into
  logs, Kafka per-user ordering, restart idempotency, container
  identity (non-root, exec-form entrypoint, deployed-artifact
  versioning), and stale or overclaimed documentation language.

## What changed, by category

Each of these has its own detailed writeup in the linked doc; this
section is a summary, not a duplicate.

- **Explanation faithfulness** — the acceptance check that gates a
  generated rewrite before it reaches a user was rewritten from a
  capitalization heuristic (which accepted fabricated lowercase claims
  like an invented actor or an invented guarantee) to a closed-vocabulary
  allow-list: any word not already in the deterministic template or a
  small set of pure grammatical scaffolding words is rejected, in any
  case, in any position. The evaluation script's own "independent"
  check was redesigned as a hand-curated blacklist of fabrication
  indicators, a structurally different mechanism from the production
  gate rather than a second copy of it. `docs/explanation-generation.md`,
  `docs/explanation-evaluation.md`.
- **Held-out evaluation integrity** — the tuning fold used to re-check
  three feature/hyperparameter decisions now refits every model it
  measures on the fit half only (previously one check reused the
  production model, which had already seen the held-out rows). Both
  the diversity-cap and freshness-threshold checks now compare the
  configured value against real alternatives, run through the actual
  production reranking algorithm, against a selection rule fixed before
  the results were seen — including one case (the diversity-cap rule)
  where that rule turned out to be flawed by construction, which is
  reported directly rather than replaced quietly. `docs/evaluation-integrity.md`.
- **Point-in-time-correct serving evaluation** — the end-to-end
  evaluation script now processes historical impressions in
  chronological order, builds each impression's durable features from
  only that impression's own recorded history, evaluates every request
  against an isolated in-memory state store (never the shared
  production Redis client), and only applies that impression's own
  events to state after scoring it — so no later event can influence an
  earlier recommendation. `docs/serving-path-end-to-end-evaluation.md`.
- **Dependency reproducibility** — `requirements-lock.txt` was
  regenerated from a complete runtime-plus-test environment (it had
  been missing `skops`, which broke test collection from a fresh
  install); a second CI job now installs from the lock file exactly and
  runs the suite. `docs/reproducibility.md`, `docs/ci-automation.md`.
- **Privacy** — the fallback path's logging now hashes the user
  identifier with the same helper the primary request path already
  used, instead of logging it raw. `docs/structured-logging.md`.
- **Time semantics** — serving code no longer falls back to naive local
  wall-clock time; every internal clock read is UTC, and an item with
  no real first-seen record is treated as unknown age rather than
  age zero (which had been making it look artificially fresh).
  Freshness reranking only runs when a request carries a real,
  historically-grounded timestamp. `docs/reranking-freshness.md`.
- **Fallback exception handling** — `safe_recommend` no longer catches
  broad built-in exception types that a real programming bug could also
  raise. A new `DependencyUnavailableError` is raised only at the three
  real per-request dependency boundaries, and only that type is caught;
  everything else propagates to the API's own error handling.
  `docs/serving-fallback.md`.
- **Request-ID and error-log preservation** — the request-ID middleware
  now wraps the downstream call in its own `try`/`except`, so an
  unhandled exception still gets a real `X-Request-ID` header and a
  correlated error log line instead of bypassing the middleware
  entirely. `docs/structured-logging.md`.
- **Kafka ordering and restart semantics** — replay events are now keyed
  by `user_id`, not `news_id`, so one user's events stay on one
  partition and arrive in order. The gap between a Redis state mutation
  and the following Kafka offset commit — a real at-least-once
  duplication risk on a crash between the two — is disclosed directly
  and demonstrated with a real test rather than papered over with
  unbuilt exactly-once machinery. `docs/streaming-consumer.md`.
- **Deployed-version tracking** — the deployed model version is now
  derived from a manifest covering every serving-critical artifact
  (retrieval model, ranking model, feature schema, catalog, embedding
  model revision, reranking configuration), not just the retrieval
  model file alone; commit identity is read from an explicit
  `GIT_COMMIT_SHA` environment variable in a container, falling back to
  local repository discovery only outside one.
- **CI and container claims** — the README no longer implies the
  containerized API itself runs in CI; it states exactly what does
  (linting, the two dependency-install paths, a real Kafka/Redis
  round trip) and what remains a locally-run, maintainer-verified check
  against the licensed MIND dataset. The container now runs as a
  non-root user, uses an exec-form entrypoint for real signal
  forwarding, and has its own health check. `docs/ci-automation.md`,
  `docs/containerization.md`.
- **Documentation language** — comments narrating "found by audit" were
  rewritten to state the current invariant or design reason directly.
  Overclaimed result language ("fully reconfirmed," "100% independently
  re-verified," "real evidence-faithfulness guarantee") was replaced
  with specific, falsifiable statements of what was actually measured
  and under what conditions.
- **Test coverage** — targeted regression tests were added for each
  category above (chronological state reconstruction, context
  isolation, Kafka partition keying, restart double-counting, UTC
  clock usage, unknown-age handling, request-ID preservation on both
  the success and failure path, raw-identifier absence from logs,
  fabricated-explanation rejection, and the tuning-decision comparison
  helpers). A CI coverage floor (`--cov-fail-under=60`, real measured
  coverage ~64%) now guards against a whole module silently losing its
  tests; it is not a target to chase upward for its own sake.

## Verification actually performed

- Full test suite, from a clean checkout of the working tree: passing
  (see the commit history for the exact count at each step; the most
  recent full run measured 311 passed).
- `ruff check .`: no findings.
- `bandit -r src/recommender -ll`: no findings at the low-severity floor.
- `docker compose config`: valid.
- A fresh virtual environment, installed exclusively from
  `requirements-lock.txt` plus `pip install --no-deps -e .`, running the
  full suite: passing.
- A real, rebuilt container: non-root user confirmed
  (`docker exec ... id` → `uid=1000(app)`), exec-form entrypoint
  confirmed (`docker compose ps` → `sh -c 'exec uvicorn…'`), health
  check confirmed (`docker inspect
  --format='{{.State.Health.Status}}'` → `healthy`), and live
  `/health`, `/ready`, `/recommend`, `/demo`, and `/metrics` requests
  confirmed against it, including the full artifact manifest and
  derived `serving_version` appearing in `/metrics`, and a
  UTC-suffixed `generated_at` on a real response body.
- Commit identity inside a container with no `.git` directory:
  `GIT_COMMIT_SHA=$(git rev-parse HEAD) docker compose build api`,
  then `docker exec recommender-api python -c "from
  recommender.tracking.experiment_log import _current_git_commit;
  print(_current_git_commit())"` resolved the real commit, confirming
  the environment-variable path works where repository discovery
  cannot.
- Real Kafka produce/consume round trip
  (`python -m recommender.streaming.verify_connectivity` →
  `consumed_value_matches: true`) and real Redis round trip with
  latency (`python -m recommender.features.verify_state_store` →
  `round_trip_matches: true`, p50 0.51 ms, p99 1.61 ms) against the
  live Compose stack.
- Redis authentication and persistence, against the current Compose
  file: unauthenticated `ping` rejected with `NOAUTH`, a wrong
  password rejected with `WRONGPASS`, the correct password accepted,
  and a written key still present after a real `docker restart` of the
  Redis container.
- `evaluate_end_to_end.py`, `verify_tuning_decisions.py`, and
  `evaluate_explanations.py` were each re-run against the real, local,
  licensed MIND data, and the documentation pages linked above report
  the real numbers those runs produced — including the disappointing
  ones (all four serving-path ranking-quality metrics measured 0.0 in
  the current evaluation window; see
  `docs/serving-path-end-to-end-evaluation.md` for why, and for
  catalog- and feature-coverage numbers reported alongside it rather
  than in place of it).

## Real, disclosed limitations

- **`pip-audit` could not be run to completion on this development
  machine.** It reaches out to PyPI's JSON API directly (not through
  `pip`, so `pip`'s own trusted-host configuration doesn't apply to it)
  and every attempt — including with `certifi`'s CA bundle set
  explicitly via `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` — failed the same
  way: `SSLCertVerificationError: unable to get local issuer
  certificate`, consistent with this machine's network intercepting
  TLS in a way that isn't resolved by pointing at a standard CA bundle.
  `pip-audit` therefore runs as a blocking step in the
  `locked-install-test` CI job instead, against the exact locked
  versions, where no such interception exists. Until that job has run,
  no vulnerability result exists for this project.
- **`requirements-lock.txt` is a plain `pip freeze` output, not a
  hash-verified lock.** The audit that prompted this review preferred a
  hash-verified lock produced with `uv` or `pip-compile
  --generate-hashes`; that tooling was not adopted here. The lock file
  was verified to install cleanly and completely in a fresh environment
  (the concrete problem it exists to catch), but it does not protect
  against a compromised package matching its pinned version number.
- **The diversity-cap comparison rule in `verify_tuning_decisions.py`
  does not work as intended.** It is described honestly in
  `docs/evaluation-integrity.md`: because relevance-vs-diversity is
  monotonic across cap values, any rule that measures against the
  uncapped case trivially favors the smallest cap tried, independent of
  the real tradeoff. The tradeoff table it produces is real and useful;
  the rule's own automatic selection is not a meaningful answer to
  "which cap is best."
- **The recency-leakage explanation for the popularity-feature
  discrepancy is supported, not proven.** A chronological re-split
  reproduces a result consistent with the hypothesis, but fit and tune
  also differ in which users and impressions land on each side of a
  chronological boundary versus a random one — a real confound this
  check does not separately isolate.
- **The serving path effectively does not surface a user's next click.**
  Follow-up investigation established the cause and it is not a
  measurement artifact: the clicked item is among the 50 retrieved
  candidates in only 0.2% of impressions, a hard ceiling no ranking
  improvement can lift. Two contributing defects were found and fixed
  along the way — the evaluation seeded no point-in-time history, and
  the serving path queried the index with a zero-norm vector for
  history-less users — and fixing them raised recent-feature coverage
  from 8.2% to 97.8% and roughly quadrupled catalog coverage, but did
  not materially move ranking quality. The underlying constraint is the
  one `docs/retrieval-evaluation.md` already named: the item tower's
  category/subcategory-only features collapse 51,282 items into 284
  distinct vectors. Retrieval depth (50 of 51,282) is a second measured
  factor, deliberately left unchanged because tuning it against
  `validation` would repeat the leakage this review corrected. This
  remains open, now with a specific diagnosis rather than an
  unexplained zero.
- **No dedicated DST-transition test exists** for the timezone fix.
  The fix itself is structural (every internal clock read is UTC,
  which has no daylight-saving transitions to be wrong about), so the
  class of bug is eliminated by construction rather than covered by a
  specific transition-boundary test — a narrower claim than "tested
  under every DST edge case."
