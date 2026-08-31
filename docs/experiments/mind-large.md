# MIND-large ingestion check

The existing ingestion code processes the larger official MIND release
without modification.

Implementation: `src/recommender/data/verify_mind_large.py`.

## Same source, same code, larger files

Both archives came from the same mirror documented in
[dataset source](../dataset-source.md):

| Archive | Bytes |
|---|---:|
| `MINDlarge_train.zip` | 531,360,717 |
| `MINDlarge_dev.zip` | 103,592,887 |

`zipfile.testzip()` verifies each archive. The unchanged `ingest_split`
function passes the normal schema checks and writes the usual Parquet
shape under `data/processed/mind_large/`.

## Numbers, both splits

| Split | News rows | News scale | Behaviors rows | Behaviors scale | Extract | Ingest |
|---|---|---|---|---|---|---|
| train | 101,527 | 1.98× | 2,232,748 | **14.22×** | 11.8s | 19.9s |
| dev | 72,023 | 1.70× | 376,471 | **5.15×** | 2.4s | 4.2s |

## Scale difference

The article catalog grows by about 1.7–2.0×, while behavior rows grow by
5.15–14.22×. MIND-large therefore adds interaction density much faster
than article supply.

Coverage and quality may differ at this scale, but this check does not
measure them.

## What this check deliberately does not do

This check does not:

- retrain retrieval or ranking models;
- rerun quality evaluation;
- compare MIND-small and MIND-large metrics; or
- profile memory and CPU on the larger data.

Those would be separate experiments using the same metric definitions,
not part of ingestion compatibility.

See [data quality](data-quality.md) and
[historical performance profile](profile-hotspots.md).
