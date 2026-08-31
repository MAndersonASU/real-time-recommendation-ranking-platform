# Explanation evidence lookup

Explanations use the existing article catalog. They do not create a
second document index or knowledge base.

Implementation: `src/recommender/explanation/retrieval.py`.

## What gets retrieved

```python
@dataclass(frozen=True)
class SupportContext:
    news_id: str
    title: str
    category: str
    subcategory: str
    abstract: str        # truncated to 300 characters
    category_match: bool
    content_similarity: float
    retrieval_score: float
    user_history_length: int
```

`retrieve_support_context(request, news_by_id)` looks up the recommended
article by `news_id` in `news.parquet`. Title, category, subcategory, and
abstract come from that catalog.

Category match, content similarity, retrieval score, and history length
come directly from `ExplanationRequest.matched_signals`. Explanation code
does not recalculate the ranking evidence.

## Why no new knowledge base

The existing catalog already has documented source, license, and
limitations. Copying it into another store would add synchronization and
governance work without adding evidence.

## Why the abstract is truncated at retrieval time, not later

Abstracts are limited to 300 characters during lookup. This keeps later
input sizes predictable and prevents one long article from dominating
the explanation request.

A missing abstract becomes an empty string. Later code therefore handles
one string type instead of treating `None` as a special case.

See the [dataset source](../dataset-source.md) and
[explanation boundary](explanation-boundary.md).
