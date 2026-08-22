import json
from pathlib import Path

from recommender.tracking.experiment_log import log_run

REPORTS_DIR = Path("data/processed/mind_small")


def _numeric(d: dict) -> dict:
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def backfill() -> list[str]:
    """Logs every evaluation result already sitting in the real report
    files on disk (baseline_report.json through reranking_evaluation_
    report.json, all Phases 2-5) as a structured run, reading the actual
    numbers rather than retyping them from docs by hand. Two pairs of
    runs share a near-identical name in the source data but measure
    genuinely different things -- kept distinct here rather than
    collapsed, exactly the kind of mix-up a structured log is meant to
    prevent:

    - retrieval_full_catalog_n100 (docs/retrieval-evaluation.md): the
      two-tower model alone, searching the whole ~51k-item catalog.
    - retrieval_score_as_sort_key_k10 (docs/ranking-evaluation.md): the same model's raw
      score, used only to sort MIND's own small frozen candidate pool --
      a much easier task, and a much higher number, for a real, disclosed
      reason (docs/inference-path.md).
    """
    logged = []

    baseline = json.loads((REPORTS_DIR / "baseline_report.json").read_text())
    for name, result in baseline.items():
        run_name = f"baseline_{name}_k10"
        log_run(
            run_name,
            params={"k": result["k"], "split": "validation"},
            metrics=_numeric(result),
            notes="Phase 2 -- non-learned baseline over MIND's own frozen impression candidates",
        )
        logged.append(run_name)

    retrieval = json.loads((REPORTS_DIR / "retrieval_evaluation_report.json").read_text())
    log_run(
        "retrieval_full_catalog_n100",
        params={"n": retrieval["n"], "split": "validation"},
        metrics=_numeric(retrieval),
        notes="Phase 3 retrieval evaluation -- two-tower retrieval alone, full catalog, N=100",
    )
    logged.append("retrieval_full_catalog_n100")

    ranking = json.loads((REPORTS_DIR / "ranking_evaluation_report.json").read_text())
    log_run(
        "retrieval_score_as_sort_key_k10",
        params={"k": ranking["retrieval_score_only"]["k"], "split": "validation"},
        metrics=_numeric(ranking["retrieval_score_only"]),
        notes="Phase 4 ranking evaluation -- retrieval_score as sort key over the frozen candidate pool, not the full catalog",
    )
    log_run(
        "ranking_model_k10",
        params={"k": ranking["ranked"]["k"], "split": "validation"},
        metrics=_numeric(ranking["ranked"]),
        notes="Phase 4 ranking evaluation -- trained logistic regression ranking model",
    )
    logged.extend(["retrieval_score_as_sort_key_k10", "ranking_model_k10"])

    reranking = json.loads((REPORTS_DIR / "reranking_evaluation_report.json").read_text())
    log_run(
        "reranking_ranked_only_k10",
        params={"k": reranking["k"], "split": "validation"},
        metrics=_numeric(reranking["ranked_only"]),
        notes="Phase 5 reranking evaluation -- ranking model's own output, before reranking",
    )
    log_run(
        "reranking_diverse_fresh_k10",
        params={"k": reranking["k"], "split": "validation"},
        metrics=_numeric(reranking["reranked"]),
        notes="Phase 5 reranking evaluation -- diversity + freshness reranking applied",
    )
    logged.extend(["reranking_ranked_only_k10", "reranking_diverse_fresh_k10"])

    return logged


def main() -> None:
    logged = backfill()
    print(f"Logged {len(logged)} runs: {logged}")


if __name__ == "__main__":
    main()
