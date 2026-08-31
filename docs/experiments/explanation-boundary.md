# Explanation boundary

Explanation code describes a completed recommendation. It cannot choose
or reorder candidates.

The type contract enforces this boundary:

- `src/recommender/explanation/contract.py`
- `src/recommender/serving/contract.py`

## The contract

```python
class MatchedSignals(BaseModel):
    category_match: bool
    content_similarity: float
    retrieval_score: float
    user_history_length: int

class ExplanationRequest(BaseModel):
    user_id: str
    recommended_item: RecommendedItem   # already ranked, already final
    matched_signals: MatchedSignals     # the real features that ranked it

class ExplanationResponse(BaseModel):
    news_id: str
    explanation: str
    refused: bool
    evidence_used: list[str]
```

## Why one request contains one item

`ExplanationRequest` contains one already-ranked `RecommendedItem` and
the signals that supported its score. It has no candidate pool and no
raw user history.

The explanation component therefore lacks the data needed to make
another ranking decision.

## `MatchedSignals`: real values, never recomputed

`recommend()` accepts `include_matched_signals`, which defaults to
`False`. When enabled, it copies category match, content similarity,
retrieval score, and history length from the same feature row used for
ranking.

The explanation path does not rerun feature computation. `hour_of_day`
is not exposed, and `popularity` is not a trained model input.

## `build_explanation_requests`: the boundary in code, not just in prose

```python
def build_explanation_requests(response: RecommendationResponse) -> list[ExplanationRequest]:
```

This function accepts only a completed `RecommendationResponse`. It
raises when matched signals were not requested. It has no route back
into retrieval, ranking, or reranking.

## Why `refused` is a required field, not inferred from empty text

When evidence is insufficient, the response must say so.
`refused` is required rather than inferred from empty text, so callers
can reliably distinguish an explanation from a refusal.

See [ranking features](ranking-features.md) and
[explanation evaluation](explanation-evaluation.md).
