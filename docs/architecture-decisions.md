# Architecture decisions

Dated record of structural decisions and why they were made. This is a
historical log: entries describe the state of the project on the date
shown, not necessarily the current design. For current architecture see
[`docs/architecture.md`](architecture.md).

- **2026-08-15** — Fresh start: the prior local checkout and GitHub
  repository no longer existed when work began; nothing carried forward
  from any earlier attempt.
- **2026-08-15** — Python pinned to 3.11 rather than the machine's
  system-default 3.14, since PyTorch, Faiss and TorchRec typically lag
  behind the newest CPython release.
- **2026-08-15** — Dependencies are added only when the component that
  needs them is built, rather than declared up front, to avoid stale or
  unused pins accumulating over a long-running project.
- **2026-08-15** — `.gitignore`'s initial `data/` pattern was unanchored
  and matched `src/recommender/data/` (a source package) in addition to
  the intended root-level dataset folder. Caught by reading `git status`
  after staging, before the first commit; fixed by anchoring the pattern
  to `/data/`.
- **2026-08-15** — CI runs on `ubuntu-latest` rather than mirroring local
  Windows development, since the codebase is pure Python with no
  OS-specific behaviour. Revisit if a dependency introduces
  platform-specific build requirements.
- **2026-08-15** — The research contract
  ([`docs/research-scenario.md`](research-scenario.md)) was frozen before
  any repository or code existed, including an explicit separation
  between N (retrieval-stage candidate count) and K (served Top-K), since
  RQ1 and RQ2 evaluate different quantities and must not be conflated in
  reporting.
- **2026-08-16** — Added `recommender.evaluation`, a ninth subpackage not
  present in the original eight-package skeleton. Metric definitions
  (Recall@K, NDCG@K, MRR, hit rate, coverage) don't belong to any single
  existing package: they are not the ranking model itself
  (`recommender.ranking`), and they are consumed by both the offline
  evaluation path and the online replay path, so folding them into either
  one would misattribute ownership. A dedicated package keeps the metric
  contract in one place both paths import from.
- **2026-08-16** — The baselines live in
  `recommender/ranking/baselines.py`, inside the package already planned
  for the learned ranking model, rather than a new top-level package. A
  popularity ranker and a learned ranker do the same conceptual job —
  order a fixed set of candidates — so they share a module rather than
  each baseline earning its own package, which would multiply the module
  count faster than the complexity justifies.
- **2026-08-21** — Added `recommender.tracking`, a tenth subpackage, for
  a plain JSONL experiment log
  ([`docs/experiments/experiment-tracking.md`](experiments/experiment-tracking.md)). MLflow —
  named in the original stack outline as a conditional addition — was
  evaluated with a dependency dry run and rejected: it would downgrade
  the pinned pandas version and add roughly 60 transitive packages for a
  solo project with about a dozen experiments, more machinery than the
  need justifies.
- **2026-08-22** — Added `recommender.explanation`, an eleventh
  subpackage, for the optional generative explanation layer
  ([`docs/experiments/explanation-boundary.md`](experiments/explanation-boundary.md)). Kept
  separate from `recommender.serving` deliberately: the explanation layer
  only ever consumes a finished `RecommendationResponse`, and a shared
  package could make it easy to accidentally give it access to
  in-progress ranking state it should never see.
