# Retrieving Support Context

The "retrieval" half of this project's RAG extension is a lookup
against a catalog this project already governs, not a new knowledge
base built specifically for it. Implementation:
`src/recommender/explanation/retrieval.py`.

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

`retrieve_support_context(request, news_by_id)` looks up the
recommended item's real title, category, subcategory, and abstract
from `news.parquet` — the same governed catalog every component since
data ingestion has used (`docs/dataset-source.md`), indexed once by `news_id`
per the same convention `ServingContext.category_by_id` already uses.
The four ranking signals are carried straight through from
`ExplanationRequest.matched_signals` (`docs/explanation-boundary.md`),
never recomputed.

## Why no new knowledge base

Standing up a separate document index or vector store for this would
introduce a second copy of data this project already licenses,
governs, and has fully described the limitations of. Reusing the one
real source makes "governed knowledge source" literally true rather
than a description of a newly introduced, separately-tracked dataset.

## Why the abstract is truncated at retrieval time, not later

A raw `abstract` field is unbounded. Handed straight into a generation
prompt, a very long abstract could crowd out the actual instruction in
a small model's limited context window, and different articles would
produce wildly different prompt sizes. Truncating at 300 characters
here, before the value ever leaves this check, keeps every later stage's
input size predictable regardless of which article gets recommended. A
missing abstract (`None` in the raw catalog) is treated as an empty
string, not passed through as `None` — a generation routine should never
have to special-case a null value that only ever means "no abstract
exists for this item."
