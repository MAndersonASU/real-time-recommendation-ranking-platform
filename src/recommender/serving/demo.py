from functools import lru_cache

import pandas as pd

from recommender.evaluation.contract import load_catalog
from recommender.explanation.contract import build_explanation_requests
from recommender.explanation.generation import generate_explanation
from recommender.explanation.retrieval import retrieve_support_context
from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext

STAGE_ORDER = [
    "feature_lookup_ms",
    "embedding_ms",
    "retrieval_ms",
    "feature_build_ms",
    "ranking_ms",
    "reranking_ms",
]
STAGE_LABELS = {
    "feature_lookup_ms": "Feature lookup",
    "embedding_ms": "User embedding",
    "retrieval_ms": "Candidate retrieval",
    "feature_build_ms": "Feature building",
    "ranking_ms": "Ranking",
    "reranking_ms": "Reranking",
}
DEFAULT_NUM_CANDIDATES = 5


@lru_cache(maxsize=1)
def _news_by_id() -> pd.DataFrame:
    return load_catalog().set_index("news_id")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_demo_data(
    user_id: str,
    context: ServingContext,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
    news_by_id: pd.DataFrame | None = None,
) -> dict:
    """Calls the real pipeline exactly once, with both `stage_timings`
    and `include_matched_signals` turned on, and derives every value
    the demo page shows from that single response -- never a second,
    separately-computed number for display purposes.

    Goes through `safe_recommend`, not `recommend` directly (a real bug,
    found by audit: this previously called `recommend()` directly, so a
    real dependency failure -- an unreachable Redis, a corrupted model
    file -- crashed this page with an unhandled 500 instead of degrading
    to the same popularity fallback `/recommend` already falls back to).
    A fallback response never has matched signals, so no explanation
    renders for that item -- an honest reflection of not having run the
    real personalized path, not a bug in the explanation layer.

    `news_by_id` defaults to the real, cached catalog load; tests pass
    a small synthetic frame instead, the same dependency-injection
    pattern already used for the explanation layer's own generator.
    """
    stage_timings: dict[str, float] = {}
    request = RecommendationRequest(user_id=user_id, num_candidates=num_candidates)
    response = safe_recommend(
        request, context, stage_timings=stage_timings, include_matched_signals=True
    )

    news_by_id = news_by_id if news_by_id is not None else _news_by_id()
    explanations = {}
    if response.matched_signals is not None:
        for explanation_request in build_explanation_requests(response):
            support = retrieve_support_context(explanation_request, news_by_id)
            explanations[support.news_id] = generate_explanation(support)

    items = []
    for item in response.recommendations:
        title = news_by_id.loc[item.news_id, "title"] if item.news_id in news_by_id.index else item.news_id
        explanation = explanations.get(item.news_id)
        items.append(
            {
                "rank": item.rank,
                "news_id": item.news_id,
                "title": title,
                "category": item.category,
                "score": item.score,
                "explanation": explanation.explanation if explanation and not explanation.refused else None,
            }
        )

    return {
        "user_id": user_id,
        "durable_features_used": response.durable_features_used,
        "recent_features_used": response.recent_features_used,
        "stage_timings_ms": {name: stage_timings.get(name, 0.0) for name in STAGE_ORDER},
        "total_ms": sum(stage_timings.values()),
        "items": items,
    }


def render_demo_html(
    user_id: str,
    context: ServingContext,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
    news_by_id: pd.DataFrame | None = None,
) -> str:
    d = build_demo_data(user_id, context, num_candidates, news_by_id=news_by_id)

    stage_rows = "".join(
        f'<tr><td class="label">{STAGE_LABELS[name]}</td>'
        f'<td class="value">{d["stage_timings_ms"][name]:.2f} ms</td></tr>'
        for name in STAGE_ORDER
    )

    item_rows = []
    for item in d["items"]:
        explanation_html = (
            f'<div class="explanation">{_escape(item["explanation"])}</div>'
            if item["explanation"]
            else '<div class="explanation muted">(no explanation: insufficient evidence)</div>'
        )
        item_rows.append(
            f'<tr><td>{item["rank"]}</td>'
            f'<td>{_escape(str(item["title"]))}</td>'
            f'<td>{_escape(item["category"] or "")}</td>'
            f'<td class="value">{item["score"]:.3f}</td></tr>'
            f'<tr><td></td><td colspan="3">{explanation_html}</td></tr>'
        )

    personalization = (
        "Fully personalized"
        if d["durable_features_used"] and d["recent_features_used"]
        else "Partially personalized"
        if d["durable_features_used"] or d["recent_features_used"]
        else "Cold start (no known features)"
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Recommendation Demo &mdash; {_escape(d["user_id"])}</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #F3F5F6; color: #1B2430; margin: 0; padding: 2rem; }}
h1 {{ font-family: Georgia, serif; font-weight: 400; font-size: 1.4rem; margin-bottom: 0.3rem; }}
.status {{ color: #4C5966; margin-bottom: 1.5rem; font-size: 0.92rem; }}
h2 {{ font-family: monospace; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: #7C8792; margin: 1.6rem 0 0.5rem; }}
table {{ border-collapse: collapse; width: 100%; max-width: 640px; background: #fff; border-radius: 8px; overflow: hidden; }}
td, th {{ padding: 0.55rem 0.9rem; border-bottom: 1px solid #E8ECEE; text-align: left; font-size: 0.88rem; }}
.value {{ text-align: right; font-family: monospace; font-weight: 700; color: #276E6B; }}
.explanation {{ font-size: 0.82rem; color: #4C5966; padding-top: 0; font-style: italic; }}
.explanation.muted {{ color: #A6AFB6; }}
</style></head>
<body>
<h1>Recommendation Demo</h1>
<p class="status">User <code>{_escape(d["user_id"])}</code> &mdash; {personalization} &mdash; total latency {d["total_ms"]:.2f} ms</p>

<h2>Per-stage latency</h2>
<table>{stage_rows}</table>

<h2>Ranked slate</h2>
<table>{"".join(item_rows)}</table>
</body></html>"""
