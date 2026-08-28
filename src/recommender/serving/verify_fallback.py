import json

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.paths import mind_small_path
from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import build_serving_context

REPORT_PATH = mind_small_path("fallback_verification_report.json")


def verify_fallback() -> dict:
    """Builds the real serving context against the real catalog, model,
    and ranking pipeline, then points its Redis client at a port nothing
    is listening on -- a real, unmocked connection failure, not a
    simulated one -- and confirms `safe_recommend` still returns a full,
    valid, contract-conforming response instead of raising.

    Uses a real user with a genuine durable-feature record (not an
    arbitrary id), specifically to show the degraded path is not the
    flat popularity fallback: `durable_features_used` comes back True,
    and `is_fallback` False, because Redis being unreachable only
    empties the recent-clicks input -- durable features and the trained
    ranking model still run for real (`docs/operations/serving-fallback.md`).
    """
    context = build_serving_context()
    context.redis_client = redis.Redis(
        host="localhost", port=6390, socket_connect_timeout=0.2, socket_timeout=0.2,
        decode_responses=True, retry=Retry(NoBackoff(), 0), retry_on_error=[],
    )

    fell_back = {"value": False, "reason": None}
    demo_user_id = next(iter(context.durable_cache.features_by_user))
    request = RecommendationRequest(user_id=demo_user_id, num_candidates=10)
    response = safe_recommend(request, context, on_fallback=lambda reason: fell_back.update(value=True, reason=reason))

    return {
        "recommendation_count": len(response.recommendations),
        "is_fallback": fell_back["value"],
        "durable_features_used": response.durable_features_used,
        "recent_features_used": response.recent_features_used,
        "all_scores_bounded": all(0.0 <= item.score <= 1.0 for item in response.recommendations),
        "top_item": response.recommendations[0].news_id,
    }


def main() -> None:
    report = verify_fallback()
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
