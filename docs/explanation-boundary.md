# The Explanation Boundary

A generative layer added to an already-working recommendation system
can, without a deliberate boundary, quietly become a second
decision-maker. This document defines the contract that makes that
structurally impossible rather than merely discouraged. Implementation:
`src/recommender/explanation/contract.py`,
`src/recommender/serving/contract.py`.

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

## Why the request type can only ever hold one already-decided item

`ExplanationRequest` has no field that could hold a candidate pool or a
user's raw history — only a single `RecommendedItem` and the
`MatchedSignals` that produced its score. If this type accepted a list
of candidates instead, nothing would stop a future caller from asking
the explanation layer to also pick the best one, quietly turning a
describe-only feature into a second, uncoordinated ranking path. Making
the type itself unable to hold that information closes the door
structurally, not just by convention.

## `MatchedSignals`: real values, never recomputed

`recommend()` (`src/recommender/serving/pipeline.py`) gained an opt-in
`include_matched_signals` parameter, defaulting to `False` so an
ordinary request pays no extra cost. When `True`, it captures each
recommended item's real `category_match`, `content_similarity`,
`retrieval_score`, and `user_history_length` directly from the same
feature row already used to produce that item's ranking score — not a
second pass over the data, and not a value derived specifically for
explanation purposes. These are the same four features documented in
`docs/ranking-features.md` (`popularity` excluded, matching the trained
model itself).

## `build_explanation_requests`: the boundary in code, not just in prose

```python
def build_explanation_requests(response: RecommendationResponse) -> list[ExplanationRequest]:
```

Takes an already-finished `RecommendationResponse` as its only input
and raises if that response wasn't built with
`include_matched_signals=True` — there is no code path from this
function back into retrieval, ranking, or reranking. It can only ever
describe a decision that has already, completely, been made elsewhere.

## Why `refused` is a required field, not inferred from empty text

This phase's own requirement is an explicit refusal when
real evidence is insufficient to explain a recommendation, not a
plausible-sounding guess produced anyway. Making `refused` a required
boolean, rather than something a caller infers from an empty
`explanation` string, means a caller can never mistake a refusal and a
real explanation for the same kind of response.
