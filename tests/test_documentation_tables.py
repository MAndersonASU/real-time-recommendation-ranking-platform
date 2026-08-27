"""Table-cell-precise checks that published numbers match their reports.

``test_documentation.NUMERIC_SYNC`` asserts a formatted number appears
*somewhere* in a document. That is not precise enough: a stale table
cell passes as long as the correct value happens to appear anywhere
else in the same file -- which is exactly how wrong MRR and catalog-
coverage figures in ranking-evaluation.md's own comparison table went
undetected, while the substring check for other cells on the same
report kept passing.

This module parses each Markdown pipe-table into rows and columns, so a
check names an exact (table, row, column) cell and nothing else can
satisfy it.
"""

from __future__ import annotations

import json
import re

import pytest

from tests.test_documentation import DOCS, REPORTS

Table = list[list[str]]


def parse_tables(text: str) -> list[Table]:
    """Every Markdown pipe-table in ``text``, as rows of stripped cells.

    A table is a header row, a ``|---|---|`` separator row, and one or
    more data rows, each starting with ``|``. Cells are split on ``|``
    and stripped; a leading/trailing empty cell from the row's own
    outer pipes is dropped.
    """
    lines = text.splitlines()
    tables: list[Table] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("|") or i + 1 >= len(lines):
            i += 1
            continue
        sep = lines[i + 1].strip()
        if not re.fullmatch(r"\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?", sep):
            i += 1
            continue
        rows = [_split_row(line)]
        j = i + 2
        while j < len(lines) and lines[j].strip().startswith("|"):
            rows.append(_split_row(lines[j]))
            j += 1
        tables.append(rows)
        i = j
    return tables


def _split_row(line: str) -> list[str]:
    cells = line.strip().split("|")
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _norm(s: str) -> str:
    return re.sub(r"\*\*|`", "", s).strip().lower()


def cell(tables: list[Table], header_marker: str, row_label: str, column_header: str) -> str:
    """The exact cell at ``row_label`` x ``column_header`` in the first
    ``header_marker``-matching table that actually contains ``row_label``.

    A document can hold two tables sharing the same header shape -- a
    current result and a superseded one kept alongside it, or two
    unlabelled ``| | Impressions | Miss rate |`` tables in the same
    file -- so matching on the header alone is not enough to pick the
    right one. Trying every header match in file order and taking the
    first that has the row asked for resolves that without needing a
    unique marker per table.
    """
    candidates = [t for t in tables if header_marker.lower() in _norm(" | ".join(t[0]))]
    assert candidates, f"no table with header containing {header_marker!r}"
    tried = []
    for table in candidates:
        header = table[0]
        col_idx = next(
            (i for i, h in enumerate(header) if _norm(column_header) == _norm(h)), None
        )
        if col_idx is None:
            tried.append(f"header {header!r} has no column {column_header!r}")
            continue
        for row in table[1:]:
            if row and _norm(row[0]) == _norm(row_label):
                assert col_idx < len(row), f"row {row!r} has no column {col_idx}"
                return row[col_idx]
        tried.append(f"rows {[r[0] for r in table[1:] if r]} has no {row_label!r}")
    raise AssertionError(
        f"no {header_marker!r}-matching table has row {row_label!r}, column "
        f"{column_header!r}: {tried}"
    )


def _report(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def _doc(name: str) -> str:
    matches = sorted(DOCS.rglob(name))
    assert matches, f"{name} not found under docs/"
    return matches[0].read_text(encoding="utf-8")


def _get(doc: dict, path: tuple[str, ...]):
    value = doc
    for key in path:
        value = value[key]
    return value


# (report, json path, format spec, document, header marker, row label, column header)
TABLE_SYNC: tuple[tuple, ...] = (
    # ranking-evaluation.md: retrieval-only vs ranked, every headline metric.
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "hit_rate_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "Hit rate@10", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "hit_rate_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "Hit rate@10", "Ranked"),
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "recall_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "Recall@10", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "recall_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "Recall@10", "Ranked"),
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "ndcg_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "NDCG@10", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "ndcg_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "NDCG@10", "Ranked"),
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "mrr"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "MRR", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "mrr"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "MRR", "Ranked"),
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "catalog_coverage_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "Catalog coverage@10", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "catalog_coverage_at_k"), ".4f",
     "ranking-evaluation.md", "retrieval score only", "Catalog coverage@10", "Ranked"),

    # ranking-evaluation.md: the same two cells again in the wider
    # "every model measured so far" comparison table -- the second
    # table this cell's fix has to land in, checked by a header marker
    # ("popularity") only that table's header contains.
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "mrr"), ".4f",
     "ranking-evaluation.md", "popularity", "MRR", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "mrr"), ".4f",
     "ranking-evaluation.md", "popularity", "MRR", "Ranked"),
    ("ranking-evaluation.json", ("results", "retrieval_score_only", "catalog_coverage_at_k"), ".4f",
     "ranking-evaluation.md", "popularity", "Catalog coverage@10", "Retrieval score only"),
    ("ranking-evaluation.json", ("results", "ranked", "catalog_coverage_at_k"), ".4f",
     "ranking-evaluation.md", "popularity", "Catalog coverage@10", "Ranked"),

    # reranking-evaluation.md: ranked-only vs reranked, every headline metric.
    ("reranking-evaluation.json", ("results", "ranked_only", "hit_rate_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "Hit rate@10", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "hit_rate_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "Hit rate@10", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "recall_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "Recall@10", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "recall_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "Recall@10", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "ndcg_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "NDCG@10", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "ndcg_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "NDCG@10", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "mrr"), ".4f",
     "reranking-evaluation.md", "ranked only", "MRR (slate-scoped)", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "mrr"), ".4f",
     "reranking-evaluation.md", "ranked only", "MRR (slate-scoped)", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "mean_distinct_categories"), ".2f",
     "reranking-evaluation.md", "ranked only", "Mean distinct categories", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "mean_distinct_categories"), ".2f",
     "reranking-evaluation.md", "ranked only", "Mean distinct categories", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "mean_max_category_count"), ".2f",
     "reranking-evaluation.md", "ranked only", "Mean max-category count", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "mean_max_category_count"), ".2f",
     "reranking-evaluation.md", "ranked only", "Mean max-category count", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "mean_fresh_fraction"), ".4f",
     "reranking-evaluation.md", "ranked only", "Mean fresh fraction", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "mean_fresh_fraction"), ".4f",
     "reranking-evaluation.md", "ranked only", "Mean fresh fraction", "Reranked"),
    ("reranking-evaluation.json", ("results", "ranked_only", "catalog_coverage_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "Catalog coverage@10", "Ranked only"),
    ("reranking-evaluation.json", ("results", "reranked", "catalog_coverage_at_k"), ".4f",
     "reranking-evaluation.md", "ranked only", "Catalog coverage@10", "Reranked"),

    # ablations.md: retrieval-features ablation, every headline metric.
    ("ablation.json", ("results", "full_model", "hit_rate_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "Hit rate@10", "Full ranking model"),
    ("ablation.json", ("results", "no_retrieval_score_feature", "hit_rate_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "Hit rate@10", "Retrieval feature removed"),
    ("ablation.json", ("results", "full_model", "recall_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "Recall@10", "Full ranking model"),
    ("ablation.json", ("results", "no_retrieval_score_feature", "recall_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "Recall@10", "Retrieval feature removed"),
    ("ablation.json", ("results", "full_model", "ndcg_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "NDCG@10", "Full ranking model"),
    ("ablation.json", ("results", "no_retrieval_score_feature", "ndcg_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "NDCG@10", "Retrieval feature removed"),
    ("ablation.json", ("results", "full_model", "mrr"), ".4f",
     "ablations.md", "retrieval feature removed", "MRR", "Full ranking model"),
    ("ablation.json", ("results", "no_retrieval_score_feature", "mrr"), ".4f",
     "ablations.md", "retrieval feature removed", "MRR", "Retrieval feature removed"),
    ("ablation.json", ("results", "full_model", "catalog_coverage_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "Catalog coverage@10", "Full ranking model"),
    ("ablation.json", ("results", "no_retrieval_score_feature", "catalog_coverage_at_k"), ".4f",
     "ablations.md", "retrieval feature removed", "Catalog coverage@10", "Retrieval feature removed"),

    # failure-analysis.md: every segment's miss rate, as a percentage.
    ("failure-analysis.json", ("results", "by_user_history_length", "0", "miss_rate"), ".1%",
     "failure-analysis.md", "history length", "0 (cold-start user)", "Miss rate"),
    ("failure-analysis.json", ("results", "by_user_history_length", "1-5", "miss_rate"), ".1%",
     "failure-analysis.md", "history length", "1-5", "Miss rate"),
    ("failure-analysis.json", ("results", "by_user_history_length", "6-20", "miss_rate"), ".1%",
     "failure-analysis.md", "history length", "6-20", "Miss rate"),
    ("failure-analysis.json", ("results", "by_user_history_length", "20+", "miss_rate"), ".1%",
     "failure-analysis.md", "history length", "20+", "Miss rate"),
    ("failure-analysis.json", ("results", "by_clicked_item_coldness",
                                "cold_item_never_clicked_in_train", "miss_rate"), ".1%",
     "failure-analysis.md", "impressions", "Cold item (never clicked in train)", "Miss rate"),
    ("failure-analysis.json", ("results", "by_clicked_item_coldness", "warm_item", "miss_rate"), ".1%",
     "failure-analysis.md", "impressions", "Warm item (clicked at least once in train)", "Miss rate"),
    ("failure-analysis.json", ("results", "by_category_match",
                                "category_matched_history", "miss_rate"), ".1%",
     "failure-analysis.md", "impressions",
     "Clicked item's category matched the user's dominant history category", "Miss rate"),
    ("failure-analysis.json", ("results", "by_category_match", "category_did_not_match", "miss_rate"), ".1%",
     "failure-analysis.md", "impressions", "Did not match", "Miss rate"),

    # evaluation-integrity.md: tune-fold reconfirmation, both decisions.
    ("tuning-decisions.json", ("results", "diversity_cap", "tune_fold_four_plus_same_category_rate"), ".1%",
     "evaluation-integrity.md", "tune fold", "Diversity: 4+ same-category rate", "Tune fold"),
    ("tuning-decisions.json", ("results", "diversity_cap", "tune_fold_single_category_rate"), ".1%",
     "evaluation-integrity.md", "tune fold", "Diversity: single-category rate", "Tune fold"),

    # serving-latency.md: the two stages the reversal is about, plus totals.
    ("serving-latency.json", ("results", "by_stage", "retrieval_ms", "p50_ms"), ".2f",
     "serving-latency.md", "stage", "Candidate retrieval", "p50"),
    ("serving-latency.json", ("results", "by_stage", "reranking_ms", "p50_ms"), ".2f",
     "serving-latency.md", "stage", "Reranking (diversity + freshness)", "p50"),
    ("serving-latency.json", ("results", "total", "p50_ms"), ".2f",
     "serving-latency.md", "stage", "**Total**", "p50"),
    ("serving-latency.json", ("results", "total", "p99_ms"), ".2f",
     "serving-latency.md", "stage", "**Total**", "p99"),
)


def _fmt_for(spec: str, value) -> str:
    return format(float(value), spec) if spec.endswith("%") else format(value, spec)


@pytest.mark.parametrize(
    "entry",
    TABLE_SYNC,
    ids=[f"{e[3]}:{e[5]}:{e[6]}" for e in TABLE_SYNC],
)
def test_table_cell_matches_report(entry) -> None:
    """One exact table cell equals the report value it is supposed to render."""
    report_name, json_path, spec, doc_name, header_marker, row_label, column_header = entry
    report = _report(report_name)
    value = _get(report, json_path)
    expected = _fmt_for(spec, value)
    tables = parse_tables(_doc(doc_name))
    actual = cell(tables, header_marker, row_label, column_header)
    actual_norm = re.sub(r"\*\*", "", actual).strip()
    actual_norm = re.sub(r"\s*ms$", "", actual_norm)  # serving-latency.md's unit suffix
    assert actual_norm == expected, (
        f"{doc_name}: cell [{row_label!r}, {column_header!r}] is {actual_norm!r}, "
        f"expected {expected!r} from {report_name}:{'.'.join(json_path)}"
    )


def test_table_cell_check_actually_catches_a_stale_value() -> None:
    """Proves the checker fails on a wrong cell, not just passes on a right one."""
    text = (
        "| Metric | Retrieval score only | Ranked |\n"
        "|---|---|---|\n"
        "| Hit rate@10 | 0.1234 | 0.6828 |\n"
    )
    tables = parse_tables(text)
    assert cell(tables, "retrieval score only", "Hit rate@10", "Retrieval score only") == "0.1234"
    report = _report("ranking-evaluation.json")
    actual_value = report["results"]["retrieval_score_only"]["hit_rate_at_k"]
    assert format(actual_value, ".4f") != "0.1234"
