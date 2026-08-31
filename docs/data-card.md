# Data card: Microsoft News Dataset (MIND)

MIND is the only real-world dataset used by this project. Microsoft
created it for news recommendation research.

Synthetic data is used for public CI and demonstrations, but never for
a published recommendation-quality result.

## Dataset versions

| Version | Use in this project |
|---|---|
| MIND-small | Development, training, evaluation, and streaming replay |
| MIND-large | Explicitly scoped scale and performance checks only |

Both versions contain:

- a news catalog with title, abstract, category, subcategory, and entity
  annotations; and
- impression logs with user histories, displayed articles, and click
  labels.

See [MIND-large evaluation](experiments/mind-large.md) for the measured
scale difference.

## Splits used here

| Project split | MIND source | Rows | Date | Use |
|---|---|---:|---|---|
| Train | Official train | 126,695 | 2019-11-09 through 2019-11-13 | Model fitting |
| Validation | Official validation day | 30,270 | 2019-11-14 | Development evaluation |
| Replay | Official dev window | 73,152 | 2019-11-15 | Streaming replay and replay evaluation |

The boundaries are chronological, not random. Tests enforce that later
data does not leak into earlier data. Replay is no longer an untouched
final set because it informed development.

See [time-aware splits](experiments/splits.md).

## Measured properties

- Overall click-through rate is about 4.04% to 4.06%.
- Only 39.6% of catalog articles receive a train-window impression.
- Only 12.7% receive a dev-window impression.
- `news` and `sports` account for 59.1% of the catalog.
- User history is empty on about 2% to 3% of rows.
- Median user activity within a window is one or two interactions.

An empty history is a real cold-start signal, not a value to impute.
See [data quality](experiments/data-quality.md).

## How the data was collected

The logs came from Microsoft News' deployed recommender. They are not a
controlled experiment.

A user could click only an article that the original system displayed.
The project's offline metrics therefore measure agreement with those
logged choices. They do not measure how users would respond to a
different set of articles.

See [limitations](limitations.md) for selection bias and unavailable
counterfactual outcomes.

## How the project processes MIND

`recommender.data.mind` reads the source files.
`recommender.data.schema` validates the records.

The ingested data is used for:

- non-learned baselines;
- two-tower retrieval training;
- ranking-model training;
- reranking policy evaluation;
- streaming replay;
- the published research conclusions.

Microsoft does not publish checksums for the original files used here.
The ingestion flow records a local SHA-256 after download. The verified
mirror's `X-Linked-ETag` is recorded separately as a source identity.

## License and distribution

MIND is governed by the Microsoft Research License Terms:

- non-commercial research use only;
- no redistribution of the dataset;
- no publication of a material portion of the dataset.

For that reason:

- raw and processed MIND files are gitignored;
- the repository contains no licensed records;
- CI never downloads MIND;
- public tests use small synthetic fixtures.

The source URLs, recorded checksums, and license review are in
[dataset source and license](dataset-source.md).

## Maintenance

The project reads MIND but does not maintain or modify the source
dataset. This card changes only when the project's use of MIND changes.
Microsoft's MIND site and license remain authoritative for dataset
identity and legal terms.

## Important limits

- User histories are sparse.
- Logged clicks contain exposure and position bias.
- No counterfactual user outcomes are available.
- The local replay feature stores began almost entirely cold: 93.6% of
  sampled replay users were absent from the durable cache, and 0% had a
  live Redis record.

The last point describes how this project's local stores were
populated. It is not a general property of MIND.
