# Dataset Source and License

## Identity

- Name: Microsoft News Dataset (MIND)
- Citation: Wu et al., ACL 2020, "MIND: A Large-scale Dataset for News Recommendation"
- Official site: https://msnews.github.io/
- Versions used: MIND-small for development; MIND-large only for
  justified, explicitly-scoped scale testing (Phase 10), per
  [`docs/research-scenario.md`](research-scenario.md)

## Canonical source (verified 2026-08-16)

The dataset's original 2019 Azure Blob Storage host is no longer the
maintained distribution point. The current canonical mirror, confirmed
against the `recommenders-team/recommenders` library's own `mind.py`
loader, is Hugging Face:

- MIND-small train: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDsmall_train.zip`
- MIND-small dev: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDsmall_dev.zip`
- MIND-large train: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDlarge_train.zip`
- MIND-large dev: `https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDlarge_dev.zip`

Total size across the Hugging Face-hosted files: approximately 1.89 GB.

Downloading via msnews.github.io additionally requires interactively
accepting the Microsoft Research License Terms (a checkbox agreement)
before the official download links activate. This step cannot be
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

No official checksums are published by Microsoft or Hugging Face for the
MIND zip files. This project computes and records its own SHA-256 hash for
each downloaded file at ingestion time (Step 1.2) as a self-consistency
check across repeated downloads on this machine — not as verification
against an authoritative source hash, since none exists to compare
against.

## What stays local-only

Per the license's no-redistribution term and this project's own
source-separation rule (see [`docs/architecture.md`](architecture.md)):
the raw and validated MIND files are never committed to this repository.
Only code, schemas, small illustrative examples that do not constitute a
material portion of the dataset, and derived metrics/reports are
committed.
