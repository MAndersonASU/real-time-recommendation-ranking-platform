from dataclasses import dataclass

import pandas as pd

from recommender.explanation.contract import ExplanationRequest

MAX_ABSTRACT_CHARS = 300


@dataclass(frozen=True)
class SupportContext:
    """Everything a generation step is allowed to draw from to explain
    one recommendation -- every field here traces to a real catalog row
    or a real ranking signal already carried on the request, nothing
    estimated or invented.
    """

    news_id: str
    title: str
    category: str
    subcategory: str
    abstract: str
    category_match: bool
    content_similarity: float
    retrieval_score: float
    user_history_length: int


def retrieve_support_context(request: ExplanationRequest, news_by_id: pd.DataFrame) -> SupportContext:
    """`news_by_id` is `news.set_index("news_id")` -- indexed once by the
    caller and reused across many requests, the same convention
    `ServingContext.category_by_id` already uses, so a lookup here costs
    one index access, not a full-table scan per explanation.

    The catalog looked up here is the same governed `news.parquet` file
    every earlier component already reads (docs/dataset-source.md) -- no
    separate knowledge base or vector store is introduced for this.
    """
    news_id = request.recommended_item.news_id
    if news_id not in news_by_id.index:
        raise ValueError(f"news_id {news_id!r} not found in the catalog")

    row = news_by_id.loc[news_id]
    abstract = row["abstract"] if isinstance(row["abstract"], str) else ""

    return SupportContext(
        news_id=news_id,
        title=row["title"],
        category=row["category"],
        subcategory=row["subcategory"],
        abstract=abstract[:MAX_ABSTRACT_CHARS],
        category_match=request.matched_signals.category_match,
        content_similarity=request.matched_signals.content_similarity,
        retrieval_score=request.matched_signals.retrieval_score,
        user_history_length=request.matched_signals.user_history_length,
    )
