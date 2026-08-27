# Dataset Source and License

## Identity

- Name: Microsoft News Dataset (MIND)
- Citation: Wu et al., ACL 2020, "MIND: A Large-scale Dataset for News Recommendation"
- Official site: https://msnews.github.io/
- Versions used: MIND-small for development; MIND-large only for
 justified, explicitly-scoped scale testing (the scale and performance work), per
  [`docs/research-scenario.md`](research-scenario.md)

## Download source (verified 2026-08-16)

This project downloaded MIND from the Recommenders Hugging Face mirror,
confirmed against the `recommenders-team/recommenders` library's own
`mind.py` loader. The official MIND site and the Microsoft Research
License remain the authoritative sources for dataset identity and
licensing; Microsoft also distributes MIND through Azure Open Datasets.
The files this project actually fetched were:

- MIND-small train: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDsmall_train.zip`
- MIND-small dev: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDsmall_dev.zip`
- MIND-large train: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDlarge_train.zip`
- MIND-large dev: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDlarge_dev.zip`

Total size across the Hugging Face-hosted files: approximately 1.89 GB.
The checksums recorded below cover exactly these downloaded files and do
not assert anything about other distributions of MIND.

Downloading via msnews.github.io additionally requires interactively
accepting the Microsoft Research License Terms (a checkbox agreement)
before the official download links activate. This check cannot be
automated from a scripted ingestion pipeline.

## License

Governed by the **Microsoft Research License Terms**
(full text: `https://github.com/msnews/MIND/blob/master/MSR%20License_Data.pdf`,
reviewed in full 2026-08-16). Key terms:

- **Permitted**: non-commercial, non-revenue-generating research use —
  teaching, academic research, public demonstrations, personal
  experimentation, analysis and testing; publishing results derived from
  the dataset.
- **Not permitted**: redistributing the dataset itself; including any
  material portion of the dataset in a publication or presentation;
  altering copyright/trademark/patent notices; implying Microsoft
  endorsement; use in malicious, deceptive, or unlawful programs.
- The dataset is licensed, not sold — Microsoft retains all rights not
  explicitly granted.
- Provided "as is," no warranty, liability capped at $5 USD, binding
  arbitration for US residents.

This project's use — non-commercial research, offline/replay
experimentation, no redistribution of the raw dataset, no publication of
raw article text or full behavior logs — fits within the granted rights as
reviewed. This summary is not legal advice; the linked PDF is the
authoritative text.

## Checksums

Microsoft does not publish checksums for the original files. The Hugging
Face mirror does, indirectly: each file's HTTP response carries an
`X-Linked-ETag` header that matches its SHA-256 content hash exactly
(verified 2026-08-16 by computing `sha256sum` on both downloaded files and
comparing against the `X-Linked-ETag` seen in a `HEAD` request against the
same URLs — both matched). This project treats that ETag as the reference
integrity value for files fetched from this specific mirror, and records
the hashes below:

| File | SHA-256 |
|---|---|
| `MINDsmall_train.zip` | `6ef97a271580b98ccfc4301ada55cc639423cb0576a78b8dcfcf74a4dbcc3194` |
| `MINDsmall_dev.zip` | `d6ce515dcaa6b6d47ddf0a326eebc8a31b84735ae410285c9882ca2a06eec669` |

This confirms the specific bytes this project ingested match what Hugging
Face served at download time; it is not an assertion that this matches
whatever Microsoft's own original files' hashes would be, since Microsoft
does not publish those for comparison.

## What stays local-only

Per the license's no-redistribution term and this project's own
source-separation rule (see [`docs/architecture.md`](architecture.md)):
the raw and validated MIND files are never committed to this repository.
Only code, schemas, small illustrative examples that do not constitute a
material portion of the dataset, and derived metrics/reports are
committed.
