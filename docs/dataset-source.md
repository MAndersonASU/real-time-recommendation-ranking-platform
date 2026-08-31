# Dataset source and license

This project uses the Microsoft News Dataset (MIND). The repository does
not include the raw dataset.

## Dataset identity

| Item | Value |
|---|---|
| Name | Microsoft News Dataset (MIND) |
| Paper | Wu et al., *MIND: A Large-scale Dataset for News Recommendation*, ACL 2020 |
| Official site | [msnews.github.io](https://msnews.github.io/) |
| Development dataset | MIND-small |
| Scale-validation dataset | MIND-large |

MIND-small is the main development dataset. MIND-large is used only when
the added scale supports a specific experiment. See the
[research scenario](research-scenario.md) for the project scope.

## Where the files came from

The project downloaded MIND from the
[Recommenders/MIND mirror on Hugging Face](https://huggingface.co/datasets/Recommenders/MIND).
Microsoft's Recommenders library uses the same mirror.

Files verified on August 16, 2026:

- [MINDsmall_train.zip](https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDsmall_train.zip)
- [MINDsmall_dev.zip](https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDsmall_dev.zip)
- [MINDlarge_train.zip](https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDlarge_train.zip)
- [MINDlarge_dev.zip](https://huggingface.co/datasets/Recommenders/MIND/resolve/main/MINDlarge_dev.zip)

The four archives require about 1.89 GB in total.

The official MIND site and its license remain the authoritative sources.
The Hugging Face links identify the exact mirror used by this project. The
official site requires a person to accept the license before downloading,
so that download cannot be automated by this repository.

## License summary

MIND is provided under the
[Microsoft Research License Terms](https://github.com/msnews/MIND/blob/master/MSR%20License_Data.pdf).
Read the full license before using the data.

In plain language, the license allows:

- noncommercial and nonrevenue research;
- teaching and public demonstrations;
- personal testing; and
- publication of results derived from the dataset.

It does not allow:

- redistributing the dataset or a substantial part of it;
- removing or changing license notices;
- implying endorsement by Microsoft; or
- malicious, deceptive, or unlawful use.

The data is licensed, not sold, and provided as-is. The terms also include
limits on liability and US arbitration provisions. The project's research
and demonstration use is consistent with these terms, but this summary is
not legal advice.

## Checksums

Microsoft does not publish checksums for these archives. For the two
MIND-small files used most often, the computed SHA-256 value matched the
Hugging Face `X-Linked-ETag` header on August 16, 2026.

| File | SHA-256 |
|---|---|
| `MINDsmall_train.zip` | `6ef97a271580b98ccfc4301ada55cc639423cb0576a78b8dcfcf74a4dbcc3194` |
| `MINDsmall_dev.zip` | `d6ce515dcaa6b6d47ddf0a326eebc8a31b84735ae410285c9882ca2a06eec669` |

These values confirm only that a local file matches the mirror bytes used
for this project. They do not prove that Microsoft published the mirror.

To verify a download on Linux or macOS:

```bash
sha256sum MINDsmall_train.zip MINDsmall_dev.zip
```

On PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 MINDsmall_train.zip, MINDsmall_dev.zip
```

## What stays outside the repository

Raw and validated dataset files remain local and are excluded by
`.gitignore`. The repository contains only:

- download and validation code;
- schemas and small illustrative examples;
- configuration files; and
- derived reports that do not reproduce the source dataset.
