import json
import time
import zipfile

from recommender.data.ingest import ingest_split
from recommender.paths import data_path, mind_small_path

RAW_ZIP_DIR = data_path("raw")
RAW_LARGE_DIR = data_path("raw_large")
PROCESSED_LARGE_DIR = data_path("processed", "mind_large")
SMALL_REPORT_PATH = mind_small_path("ingestion_report.json")
REPORT_PATH = data_path("processed", "mind_large", "ingestion_report.json")

ZIP_NAMES = {"train": "MINDlarge_train.zip", "dev": "MINDlarge_dev.zip"}


def _extract_verified(split: str) -> None:
    """Unzips one MIND-large archive after checking its own internal
    integrity (`testzip()`), the same verification already applied to
    MIND-small's ingestion -- returns the name of the first bad file, or
    None if every file's checksum matches, so a truncated download
    fails loudly here rather than surfacing as a confusing parse error
    later.
    """
    zip_path = RAW_ZIP_DIR / ZIP_NAMES[split]
    dest = RAW_LARGE_DIR / split
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        bad_file = zf.testzip()
        if bad_file is not None:
            raise RuntimeError(f"corrupt member in {zip_path}: {bad_file}")
        zf.extractall(dest)


def verify_mind_large() -> dict:
    """Extracts both real MIND-large archives, then runs the exact same,
    unmodified `ingest_split` this project has used since data ingestion
    began against them -- the actual proof this check asks for: the pipeline needs zero
    code changes to process the larger official dataset, and every metric
    definition it feeds stays exactly as frozen (docs/evaluation-
    protocol.md), since nothing about that definition is scale-dependent.
    """
    small_report = json.loads(SMALL_REPORT_PATH.read_text())

    report: dict = {"splits": {}}
    for split in ("train", "dev"):
        start = time.perf_counter()
        _extract_verified(split)
        extract_seconds = time.perf_counter() - start

        start = time.perf_counter()
        split_result = ingest_split(split, raw_dir=RAW_LARGE_DIR, processed_dir=PROCESSED_LARGE_DIR)
        ingest_seconds = time.perf_counter() - start

        small = small_report[split]
        report["splits"][split] = {
            **split_result,
            "extract_seconds": round(extract_seconds, 2),
            "ingest_seconds": round(ingest_seconds, 2),
            "news_rows_scale_factor": round(split_result["news_rows"] / small["news_rows"], 2),
            "behaviors_rows_scale_factor": round(
                split_result["behaviors_rows"] / small["behaviors_rows"], 2
            ),
        }

    return report


def main() -> None:
    report = verify_mind_large()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
