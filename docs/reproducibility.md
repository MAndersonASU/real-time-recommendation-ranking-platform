# Reproduce the environment

This page records a maintainer-run check from a new clone in an empty
directory. The check used a new virtual environment, installed all
dependencies, ran the full test suite, and started the containerized
service. It was not an independent third-party review.

## What the check proves

| Claim | Verified? | Meaning |
|---|---|---|
| A clean clone installs and passes its tests | Yes | No existing project environment was reused |
| Existing artifacts load and serve from a clean clone | Yes | The trained files are portable |
| Published experiment results can be rebuilt from the licensed data | No | Training and evaluation were not rerun |

The check copied existing offline artifacts into the new clone. It did
not reproduce any published metric, and it did not copy or redistribute
the licensed MIND dataset.

## Clean-clone check

The maintainer:

1. Cloned the public repository into an empty directory.
2. Created a new Python 3.11 virtual environment.
3. Installed the project with `pip install -e ".[dev]"`.
4. Ran the tests and lint check shown below.
5. Copied only existing derived artifacts into `data/`.
6. Started the services with `docker compose up -d --build`.
7. Called `GET /ready` and `GET /demo/{user_id}`.

Use these commands to check the code without the licensed dataset:

```bash
pytest -q
pytest -q --cov=recommender --cov-report=term-missing --cov-fail-under=60
ruff check .
```

The suite passes when `data/` is absent. Tests that once needed MIND now
use temporary synthetic artifacts and an injected catalog. Exact test
counts are omitted because they change as the suite grows. The CI badge
in the [README](../README.md) and the files under `reports/` are the
current records.

## Python version requirement

The first clean-clone attempt exposed a real setup problem. The plain
`python` command on the test machine selected Python 3.14, while this
project requires Python 3.11:

```text
ERROR: Package 'recommender' requires a different Python: 3.14.2 not in '<3.12,>=3.11'
```

The README now names Python 3.11 explicitly. This version is required
because packages such as PyTorch and Faiss may not support the newest
CPython release immediately.

## Container result

The existing project containers were stopped to release their fixed
ports and names. The clean clone then started:

- `recommender-kafka`;
- `recommender-redis`; and
- `recommender-api`.

All three reported healthy. `GET /ready` returned
`{"ready": true, ...}`. `GET /demo/U73700` returned the same ranked
slate and explanations as the original build, with normal machine-level
latency variation. The original containers were rebuilt and restored
afterward.

## Choose the correct dependency lock

The project has two lock files:

| File | Use |
|---|---|
| `requirements-lock.txt` | Runtime packages installed in the production container |
| `requirements-dev-lock.txt` | Runtime packages plus tests, linting, and audit tools |

Keeping them separate avoids installing `pytest`, `bandit`,
`pip-audit`, `ruff`, and `pip-tools` in the production image.
`pyproject.toml` declares flexible lower bounds, while the lock files
record exact packages for repeatable installation.

Regenerate both lock files after any deliberate dependency change:

```bash
pip-compile --generate-hashes --allow-unsafe \
  --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --output-file requirements-lock.txt pyproject.toml

pip-compile --generate-hashes --allow-unsafe --extra dev \
  --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --output-file requirements-dev-lock.txt pyproject.toml
```

The extra PyTorch index is required. Without it, the resolver may select
a PyPI wheel that includes several gigabytes of unused CUDA libraries.

Every pinned package includes allowed SHA-256 hashes. Installation with
`--require-hashes` stops if a downloaded artifact does not match. This
checks both the version and the file contents; `pip freeze` checks only
the version.

The locked installation previously found two defects:

- `skops` was declared in `pyproject.toml` but missing from the old
  lock; and
- an earlier check used Python 3.14 instead of Python 3.11.

Verify the development lock in a clean Python 3.11 environment:

```bash
pip install --require-hashes -r requirements-dev-lock.txt
pip install --no-deps -e .
pytest -q
```

Verify the smaller runtime lock in a separate environment by importing
the serving application:

```bash
python -m venv /tmp/runtime-env
/tmp/runtime-env/bin/pip install --require-hashes -r requirements-lock.txt
/tmp/runtime-env/bin/pip install --no-deps .
/tmp/runtime-env/bin/python -c "import recommender.serving.app"
```

Both locked installations completed successfully, and the full suite
passed. CI also checks both installation paths and scans the locked set
with `pip-audit`. See the
[CI automation guide](operations/ci-automation.md).

Do not edit lock files by hand. Their hashes must match real published
artifacts.

## Remaining limit

This check did not download MIND or rebuild the offline artifacts. A new
user must obtain MIND by following the
[dataset source and license guide](dataset-source.md), then run the
offline pipeline before the service can return real personalized
recommendations. The test suite itself needs only a clean clone.
