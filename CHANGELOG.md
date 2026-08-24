# Changelog

## 2026-08-24 — Engineering hardening and evaluation-integrity improvements

A maintainer-led engineering review across serving-path correctness,
evaluation methodology, reproducibility, and privacy handling. Full
detail: `docs/engineering-review-and-hardening.md`.

- Replaced the explanation-faithfulness heuristic with a
  closed-vocabulary allow-list; redesigned the evaluation script's own
  check as an independent blacklist mechanism.
- Rebuilt the tuning-fold decision checks to refit held-out models and
  compare against real alternative values under a predefined rule.
- Rewrote the serving-path end-to-end evaluation to be point-in-time
  correct: chronological processing, per-impression isolated state,
  no future leakage into an earlier recommendation.
- Regenerated `requirements-lock.txt` (it was missing `skops`) and
  added a CI job that installs from it exactly.
- Fixed a raw-user-id logging leak on the fallback path.
- Moved internal clock handling to UTC throughout; unknown item age is
  no longer treated as zero (artificially fresh).
- Narrowed `safe_recommend`'s exception handling to a dedicated
  dependency-failure type, so a real programming bug can no longer be
  silently reported as a successful fallback.
- Preserved the request-ID header and a correlated error log line on
  unhandled exceptions.
- Fixed Kafka replay event keying (per-user, not per-item) and
  disclosed the real at-least-once restart-duplication window with a
  demonstrating test.
- Replaced single-artifact model-version fingerprinting with a full
  serving-artifact manifest; added explicit `GIT_COMMIT_SHA`
  propagation for containers.
- Corrected README and CI-related documentation to state exactly what
  CI runs versus what remains a local, maintainer-verified check;
  added a container health check, non-root user, and exec-form
  entrypoint.
- Removed audit-history narration from source comments in favor of
  stating the current invariant directly; softened overclaimed result
  language across several docs.
- Added a CI coverage floor (`--cov-fail-under=60`).

See `docs/engineering-review-and-hardening.md` for verification
commands actually run and real, disclosed limitations (notably:
`pip-audit` could not complete on this development machine, and
`requirements-lock.txt` is not hash-verified).
