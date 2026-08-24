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

- **Retrieval quality** — the item tower encoded each article from its
  category and subcategory alone, which take only 284 distinct values
  across 51,282 items, so retrieval could identify a topic but never an
  article within it. Each article now also carries a dense content
  vector from its own title and abstract, raising distinct catalog
  embeddings from 284 to 50,704 and every retrieval metric by 7.6x to
  13.5x. Retrieval depth was separately raised from 50 to 1,000
  candidates on tuning-fold evidence. End to end, the clicked item now
  reaches the ranker 12.2% of the time against 0.2% before.
  `docs/retrieval-model.md`, `docs/retrieval-evaluation.md`,
  `docs/serving-path-end-to-end-evaluation.md`.
- **Cold-start retrieval** — a user with no click history produced an
  exactly zero-norm query vector, against which an inner-product index
  scores every item identically, so every such user received the same
  arbitrary slate with identical scores. Cold-start retrieval now draws
  from training-set popularity instead. `docs/serving-fallback.md`.
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
  production reranking algorithm. Two selection rules written for this
  work turned out not to discriminate at all — each bounded the
  *benefit* along an axis that moves monotonically with the parameter,
  so every candidate cleared the bar. Both were replaced with rules that
  bound the *cost* instead, and the failure is recorded rather than
  quietly patched. `docs/evaluation-integrity.md`.
- **Point-in-time-correct serving evaluation** — the end-to-end
  evaluation script now processes historical impressions in
  chronological order, builds each impression's durable features from
  only that impression's own recorded history, evaluates every request
  against an isolated in-memory state store (never the shared
  production Redis client), and only applies that impression's own
  events to state after scoring it — so no later event can influence an
  earlier recommendation. `docs/serving-path-end-to-end-evaluation.md`.
- **Dependency reproducibility** — `requirements-lock.txt` was missing
  `skops`, which broke test collection from a fresh install. It is now
  a hash-verified lock generated by `pip-compile --generate-hashes`, so
  `pip install --require-hashes` rejects any artifact whose SHA-256 does
  not match — a guarantee version pinning alone cannot give. A separate
  CI job installs from it and audits it with `pip-audit`.
  `docs/reproducibility.md`, `docs/ci-automation.md`.
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
  and the following Kafka offset commit — a real duplication risk on a
  crash between the two — is now closed rather than merely disclosed:
  `claim_event` stores the resulting state inside a single atomic
  `SET NX` claim, so a redelivery recovers the state that event already
  produced instead of applying it twice. `docs/streaming-consumer.md`.
- **Deployed-version tracking** — the deployed model version is now
  derived from a manifest covering every serving-critical artifact
  (retrieval model, ranking model, feature schema, catalog, embedding
  model revision, reranking configuration), not just the retrieval
  model file alone; commit identity is read from an explicit
  `GIT_COMMIT_SHA` environment variable in a container, falling back to
  local repository discovery only outside one.
- **CI and container claims** — the README states exactly what CI runs
  rather than implying more. The containerized API is now genuinely
  exercised in CI, against synthetic artifacts generated by
  `recommender.data.synthetic` so no licensed data is needed: the job
  builds the image, waits on its own health check, asserts it runs
  non-root, and makes real requests against it. The container also uses
  an exec-form entrypoint for real signal forwarding.
  `docs/ci-automation.md`, `docs/containerization.md`.
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

Items closed since the first version of this document are recorded in
`CHANGELOG.md`; what follows is what remains true.

- **This is not a competitive recommender.** After the retrieval work
  described above, hit rate@10 on the serving path is 1.45% — the user's
  real next click reaches their slate roughly once in seventy
  impressions. That is a 29x improvement on where it started and still a
  weak result for the task. Retrieval remains the binding constraint:
  the clicked item reaches the ranker 12.2% of the time, capping
  everything downstream.
- **The recency-leakage explanation is supported, not proven.** A
  chronological re-split reproduces a result consistent with the
  hypothesis, but it also changes which users and impressions land on
  each side of the boundary — a confound this check does not isolate.
- **The diversity cap rests on a budget that is a judgment, not a
  measurement.** The selection rule now genuinely discriminates between
  cap values, but which relevance budget to spend is a product decision
  this data cannot settle (`docs/evaluation-integrity.md`).
- **Retrieval depth was chosen by judgment, not by rule.** The
  predefined search-latency budget did not bind at any depth tried, so
  the decision rests on a measured recall/latency tradeoff read with
  both numbers visible. It was measured on the tuning fold rather than
  `validation`, which is the part that matters for integrity.
- **`pip-audit` has never run on the maintainer's machine.** It queries
  PyPI's JSON API directly, so `pip`'s trusted-host configuration does
  not apply, and local TLS interception fails it with
  `SSLCertVerificationError` even with `certifi`'s bundle set
  explicitly. It now runs as a blocking CI step against the
  hash-verified lock; until that job has run, no vulnerability result
  exists for this project.
- **The synthetic CI fixtures verify wiring, not quality.** The
  containerized API is now exercised in CI against generated artifacts
  (`recommender.data.synthetic`), which proves the image builds, starts
  non-root, loads its models, and answers correctly. The synthetic
  model's scores are meaningless, and no published result derives from
  them. Every quality number in this project still comes from local runs
  against the licensed MIND data.
- **The DST-transition test does not execute on Windows.** It needs
  `time.tzset`, which is POSIX-only, so it skips on the maintainer's
  machine and runs in CI. The underlying fix is structural — every
  internal clock read is UTC — so the bug class is eliminated by
  construction rather than by that test alone.
