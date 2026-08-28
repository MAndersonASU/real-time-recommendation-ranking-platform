import json

from recommender.evaluation.sampling import DEFAULT_SAMPLE_SEED
from recommender.paths import mind_small_path
from recommender.serving.pipeline import build_serving_context
from recommender.tracking.experiment_log import log_run
from recommender.tracking.replay_evaluation import evaluate_via_replay

REPORT_PATH = mind_small_path("recent_features_ablation_report.json")


def run_recent_features_ablation(sample_seed: int = DEFAULT_SAMPLE_SEED) -> dict:
    """Runs the recent-streaming-features ablation
    (docs/experiments/ablations.md) as a genuinely paired comparison:
    both arms replay the exact same seeded sample of impressions, with
    only `use_recent_features` toggled, so any difference between them
    is attributable to that one setting and nothing else about which
    impressions were selected.

    Previously run ad hoc, with no committed script producing the
    published numbers -- this is the reproducible entry point for that
    same comparison.
    """
    context = build_serving_context()
    with_recent = evaluate_via_replay(context, sample_seed=sample_seed, use_recent_features=True)
    without_recent = evaluate_via_replay(context, sample_seed=sample_seed, use_recent_features=False)

    # `assert` is unsuitable here: it is compiled out entirely under
    # `python -O` (BANDIT-REVIEW-65, Bandit B101 -- an assert used for
    # anything beyond a debugging aid is a real hazard, not a style
    # preference), which would let this specific invariant -- that both
    # arms scored the exact same sample -- silently stop being checked
    # and let an unpaired comparison continue and publish.
    with_digest = with_recent["sampling"]["selected_ids_sha256"]
    without_digest = without_recent["sampling"]["selected_ids_sha256"]
    if with_digest != without_digest:
        raise ValueError(
            "the two arms sampled different impressions -- this is no longer a paired "
            f"comparison (with_recent digest {with_digest!r}, without_recent digest "
            f"{without_digest!r})"
        )

    return {
        "with_recent_features": with_recent,
        "without_recent_features": without_recent,
        "sampling": with_recent["sampling"],
    }


def main() -> None:
    report = run_recent_features_ablation()
    with_recent = report["with_recent_features"]
    without_recent = report["without_recent_features"]

    log_run(
        "ablation_recent_features_replay_paired",
        params={
            "k": with_recent["k"],
            "impressions_sampled": with_recent["impressions_sampled"],
            "split": "replay",
            "sampling": report["sampling"],
        },
        metrics={
            "hit_rate_at_k_with_recent_features": with_recent["hit_rate_at_k"],
            "hit_rate_at_k_without_recent_features": without_recent["hit_rate_at_k"],
            "mean_feature_lookup_ms_with_recent_features": with_recent["mean_feature_lookup_ms"],
            "mean_feature_lookup_ms_without_recent_features": without_recent["mean_feature_lookup_ms"],
        },
        notes=(
            "recent-streaming-features ablation -- paired replay comparison with recent "
            "features on vs. off, same seeded impression sample in both arms "
            "(docs/experiments/ablations.md)"
        ),
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
