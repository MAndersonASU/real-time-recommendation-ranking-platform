import json
from pathlib import Path

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import build_serving_context

REPORT_PATH = Path("data/processed/mind_small/fallback_verification_report.json")


def verify_fallback() -> dict:
    """Builds the real serving context against the real catalog, model,
    and ranking pipeline, then points its Redis client at a port nothing
    is listening on -- a real, unmocked connection failure, not a
    simulated one -- and confirms `safe_recommend` still returns a full,
    valid, contract-conforming response instead of raising.
    """
    context = build_serving_context()
    context.redis_client = redis.Redis(
        host="localhost", port=6390, socket_connect_timeout=0.2, socket_timeout=0.2,
        decode_responses=True, retry=Retry(NoBackoff(), 0), retry_on_error=[],
    )

    request = RecommendationRequest(user_id="u1000", num_candidates=10)
    response = safe_recommend(request, context)

    return {
        "recommendation_count": len(response.recommendations),
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
