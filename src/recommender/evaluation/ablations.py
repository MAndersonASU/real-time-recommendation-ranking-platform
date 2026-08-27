import json
from dataclasses import dataclass
from pathlib import Path

from recommender.evaluation.contract import TOP_K, load_catalog
from recommender.evaluation.evaluate_ranking import _evaluate_by_score
from recommender.ranking.build_dataset import TRAIN_PATH, VALIDATION_PATH
from recommender.ranking.features import FEATURE_COLUMNS
from recommender.ranking.train import load_ranking_frame, train_ranking_model
from recommender.tracking.experiment_log import log_run

REPORT_PATH = Path("data/processed/mind_small/ablation_report.json")

# `popularity` is already excluded from every trained ranking model
# (recommender.ranking.train -- it scores worse than random on validation,
# docs/ranking-model.md). Dropping `retrieval_score` on top of that
# isolates the retrieval-feature ablation specifically, leaving the four
# remaining handcrafted features untouched.
NO_RETRIEVAL_SCORE_FEATURES = [c for c in FEATURE_COLUMNS if c not in ("popularity", "retrieval_score")]


@dataclass(frozen=True)
class AblationSpec:
    name: str
    component: str
    description: str
    status: str  # "new_this_step" or "reuses_existing_tracked_run"
    source: str


ABLATION_MATRIX = [
    AblationSpec(
        name="no_retrieval_score_feature",
        component="retrieval features",
        description=(
            "Ranking model retrained with retrieval_score dropped from its own "
            "input features (category_match, content_similarity, "
            "user_history_length, hour_of_day kept) -- isolates whether the "
            "learned two-tower score helps the ranker beyond the four "
            "handcrafted features."
        ),
        status="new_this_step",
        source="recommender.evaluation.ablations.run_no_retrieval_score_ablation()",
    ),
    AblationSpec(
        name="no_ranker_features",
        component="ranker features",
        description=(
            "Sorting candidates by raw retrieval_score alone, with none of the "
            "ranking model's four handcrafted features -- already computed and "
            "tracked as the ranking evaluation's own retrieval-score-only "
            "baseline, not recomputed here."
        ),
        status="reuses_existing_tracked_run",
        source="retrieval_score_as_sort_key_k10 (docs/ranking-evaluation.md)",
    ),
    AblationSpec(
        name="no_reranking",
        component="reranking",
        description=(
            "Serving the ranking model's own top-10 slate unchanged, with no "
            "diversity/freshness reranking pass -- already measured as the "
            "ranked-only row of the reranking tradeoff table."
        ),
        status="reuses_existing_tracked_run",
        source="ranking_model_k10 vs reranking_diverse_fresh_k10 (docs/reranking-evaluation.md)",
    ),
    AblationSpec(
        name="no_recent_streaming_features",
        component="recent streaming features",
        description=(
            "Online serving with RecentUserFeatures forced empty -- durable "
            "features only, as if no live Kafka/Redis feed existed -- measured "
            "against the existing replay harness (recommender.tracking."
            "replay_evaluation) with one added use_recent_features toggle."
        ),
        status="new_this_step",
        source="ablation_no_recent_features_replay vs ablation_with_recent_features_replay (docs/ablations.md)",
    ),
    AblationSpec(
        name="approximate_index",
        component="cache/index settings",
        description=(
            "Approximate (IVF, nprobe swept 1/8/32/256) Faiss search in place "
            "of the exact index -- already measured as the recall-vs-latency "
            "sweep over the candidate index."
        ),
        status="reuses_existing_tracked_run",
        source="docs/faiss-index.md (nprobe sweep)",
    ),
]


def run_no_retrieval_score_ablation(k: int = TOP_K) -> dict:
    """Trains and evaluates the retrieval-feature ablation through the
    exact same training/scoring path the real ranking model uses
    (recommender.ranking.train.train_ranking_model,
    recommender.evaluation.evaluate_ranking._evaluate_by_score), differing
    only in which feature columns are passed in.
    """
    train = load_ranking_frame(TRAIN_PATH)
    validation = load_ranking_frame(VALIDATION_PATH)
    catalog_size = len(load_catalog())

    model = train_ranking_model(train, feature_columns=NO_RETRIEVAL_SCORE_FEATURES)
    score = model.predict_proba(validation[NO_RETRIEVAL_SCORE_FEATURES].to_numpy())[:, 1]
    validation = validation.assign(no_retrieval_score_ranked=score)

    return _evaluate_by_score(validation, "no_retrieval_score_ranked", k, catalog_size)


def main() -> None:
    result = run_no_retrieval_score_ablation()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({"no_retrieval_score_feature": result}, indent=2))
    log_run(
        run_name="ablation_no_retrieval_score_k10",
        params={"k": TOP_K, "split": "validation", "feature_columns": NO_RETRIEVAL_SCORE_FEATURES},
        metrics=result,
        notes="Retrieval-feature ablation: ranking model retrained with retrieval_score dropped.",
    )
    from recommender.evaluation.evaluate_ranking import (
        REPORT_PATH as RANKING_REPORT_PATH,
    )
    from recommender.evaluation.publish import (
        output_dir_from_argv,
        publish_ablation_report,
    )

    # Deltas are measured against the full model from the same rebuild, so
    # the ablation report never compares against a stale baseline.
    full_model = json.loads(RANKING_REPORT_PATH.read_text())["ranked"]
    published = publish_ablation_report(
        {"no_retrieval_score_feature": result},
        full_model,
        output_dir=output_dir_from_argv(),
    )
    print(json.dumps(result, indent=2))
    print(f"published {published}")


if __name__ == "__main__":
    main()
