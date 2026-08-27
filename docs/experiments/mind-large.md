# Promoting to MIND-large

Validates that this project's ingestion pipeline processes the larger
official MIND release without any code changes and without redefining
any metric. Implementation: `src/recommender/data/verify_mind_large.py`.

## Same source, same code, larger files

`MINDlarge_train.zip` (531,360,717 bytes) and `MINDlarge_dev.zip`
(103,592,887 bytes) come from the same Hugging Face mirror as
MIND-small (`docs/dataset-source.md`), verified with the same
`zipfile.testzip()` integrity check used for every earlier ingestion run.
The real proof
this check asks for isn't a new script — it's that `ingest_split`, the
exact function this project has used unmodified since data ingestion, runs
against these larger files and produces valid output with zero code
changes. It does: schema validation (`recommender.data.schema`) still
passes, and the same Parquet output shape lands in
`data/processed/mind_large/`.

## Numbers, both splits

| Split | News rows | News scale | Behaviors rows | Behaviors scale | Extract | Ingest |
|---|---|---|---|---|---|---|
| train | 101,527 | 1.98× | 2,232,748 | **14.22×** | 11.8s | 19.9s |
| dev | 72,023 | 1.70× | 376,471 | **5.15×** | 2.4s | 4.2s |

## A real, non-obvious asymmetry

The catalog barely grows (about 2×) while interaction volume grows far
faster (5–14×) — MIND-large has roughly the same relative article
count as MIND-small, but a much denser interaction log per article.
That has real, direct consequences for later work: catalog coverage
percentages (`docs/experiments/data-quality.md`) will almost certainly look
different at this scale, since the same or similar number of articles
now absorbs several times more impressions each. This check doesn't
re-run those measurements — that would mean changing what "catalog
coverage" measures, exactly what this check is scoped not to do — but
the asymmetry itself is a genuine, previously unmeasured fact about how
the official large release actually differs from the small one, beyond
just "bigger."

## What this check deliberately does not do

Retraining the two-tower and ranking models on the full MIND-large
corpus is out of scope here. This check's job, stated plainly by its own
name, is validating that the pipeline *can process* the larger dataset
— not re-running every component's evaluation at the new scale, which would
risk quietly redefining what each metric measures along the way. Real
hotspot profiling on top of this larger data belongs to
`docs/experiments/profile-hotspots.md` specifically, not folded in here.
