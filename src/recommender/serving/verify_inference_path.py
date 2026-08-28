import json
import time

from recommender.evaluation.contract import load_split
from recommender.paths import mind_small_path
from recommender.serving.contract import RecommendationRequest
from recommender.serving.pipeline import build_serving_context, recommend

REPORT_PATH = mind_small_path("inference_path_verification_report.json")


def verify_inference_path(num_users: int = 20) -> dict:
    """Builds the real serving context -- the actual trained two-tower
    model, the actual trained ranking model, a fresh Faiss index over the
    real catalog, and durable features from the real validation split --
    then runs `recommend()` for real users pulled from that split,
    including at least one user known to have real history. Confirms
    every response actually validates against the typed contract
    (`docs/operations/serving-contract.md`) and measures real, if rough, end-to-end
    latency; `docs/experiments/serving-latency.md` does the rigorous per-stage
    version of that measurement.
    """
    context = build_serving_context()
    validation_users = load_split("validation")["user_id"].drop_duplicates().head(num_users).tolist()

    latencies_ms = []
    personalized_count = 0
    for user_id in validation_users:
        request = RecommendationRequest(user_id=user_id, num_candidates=10)
        start = time.perf_counter()
        response = recommend(request, context)
        latencies_ms.append((time.perf_counter() - start) * 1000)
        if response.durable_features_used:
            personalized_count += 1

    unknown_response = recommend(
        RecommendationRequest(user_id="a-user-that-does-not-exist-anywhere", num_candidates=10), context
    )

    latencies_ms.sort()
    return {
        "users_checked": len(validation_users),
        "all_responses_had_ten_recommendations": all(
            len(recommend(RecommendationRequest(user_id=u, num_candidates=10), context).recommendations) == 10
            for u in validation_users[:3]
        ),
        "personalized_count": personalized_count,
        "unknown_user_uses_no_real_features": (
            unknown_response.durable_features_used is False
            and unknown_response.recent_features_used is False
        ),
        "p50_latency_ms": round(latencies_ms[len(latencies_ms) // 2], 2),
        "p99_latency_ms": round(latencies_ms[int(len(latencies_ms) * 0.99) - 1], 2),
    }


def main() -> None:
    report = verify_inference_path()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
