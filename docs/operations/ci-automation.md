# Continuous integration

`.github/workflows/ci.yml` runs on pull requests to `main` and pushes to
`main`. GitHub Actions are pinned to commit hashes.

## Jobs

| Job | Purpose |
|---|---|
| `lint-and-test` | Flexible dependency install, lint, tests, security scan, and Compose validation |
| `locked-install-test` | Reproducible lock-file installs, full tests, report validation, and dependency audit |
| `api-container-test` | Build and exercise the API image with synthetic artifacts |
| `integration-smoke-test` | Exercise Kafka and Redis containers |

## Lint and tests

This job installs `.[dev]` from the version ranges in
`pyproject.toml`, then runs:

```bash
ruff check .
pytest -q --cov=recommender --cov-report=term-missing --cov-fail-under=60
bandit -r src/recommender -ll
docker compose config
```

The enforced coverage floor is 60%. The workflow does not publish a
“current coverage” value because that figure changes with each commit.

## Locked environments

The runtime lock is installed by itself in a new virtual environment
with hash verification. Development tools are rejected if they appear
in that runtime file, and the serving application must import from the
resulting environment.

The development lock is then installed with hash verification in the
job environment. The job runs the full test suite, validates all
committed evaluation reports, and uses `pip-audit` to block known
dependency vulnerabilities.

This catches two different problems:

- flexible dependency ranges that no longer work; and
- pinned lock files that are incomplete, altered, or vulnerable.

## API container

Licensed MIND data are not stored in the repository, so CI generates a
seeded synthetic catalog, behavior splits, and model artifacts at the
same paths used by local data.

The job then:

- builds and starts the real API container;
- waits for its Docker health check;
- confirms the process is not running as root;
- calls `/health` and `/ready`;
- verifies a recommendation body and `X-Request-ID` header;
- confirms invalid demo input returns HTTP 422; and
- checks that `/metrics` exposes the serving version.

This verifies packaging and service wiring. Synthetic results are not
used as recommendation-quality evidence.

## Kafka and Redis

The integration job starts both infrastructure containers and runs:

- a Kafka publish-and-consume round trip;
- a Redis write, read, and latency check;
- the atomic idempotency operation in real Redis;
- concurrent Redis writers with independent clients; and
- Redis append-only-file recovery after an abrupt `SIGKILL`.

Both container jobs tear down their services even when a check fails.

See [containerization](containerization.md),
[local Kafka](kafka-local.md), and
[state store](state-store.md).
