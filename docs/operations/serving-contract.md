# Serving API contract

Pydantic models validate the network boundary used by
`POST /recommend`.

Implementation:
`src/recommender/serving/contract.py`.

## Request

`RecommendationRequest` contains:

| Field | Rule |
|---|---|
| `user_id` | 1–128 characters matching `[A-Za-z0-9._:-]` |
| `num_candidates` | Integer from 1 to 50; default K=10 |
| `request_time` | Optional date and time |

The identifier allow-list rejects whitespace, control characters,
zero-width characters, and bidirectional marks before they reach Redis
keys, logs, or the demonstration page.

A timezone-aware `request_time` is converted to naive UTC at the API
boundary because the MIND timestamps used by the pipeline are naive.

## Recommended item

`RecommendedItem` contains:

| Field | Rule |
|---|---|
| `news_id` | Article identifier |
| `score` | Calibrated probability from 0 to 1 |
| `rank` | Positive, one-based position in this response |
| `category` | Optional category |

## Response

`RecommendationResponse` contains:

- the requested user ID;
- the ranked article list;
- whether durable features were found;
- whether recent Redis features were found;
- the retrieval history source;
- generation time; and
- optional matched signals for explanations.

`retrieval_history_source` is one of:

| Value | Meaning |
|---|---|
| `recent` | Usable recent Redis clicks drove retrieval |
| `durable` | Saved offline history drove retrieval |
| `global_popularity` | No usable history existed |

This value is separate from `durable_features_used` and
`recent_features_used`. Ranking can use a durable category feature even
when candidate retrieval used another source.

## Optional explanation evidence

`matched_signals` is omitted by default. When
`include_matched_signals=True`, it contains the real ranking features
already used for each returned article. The explanation layer does not
recompute them.

## Why Pydantic is used here

Internal feature objects are dataclasses because trusted Python code
creates them. API JSON is untrusted. Pydantic rejects invalid sizes,
patterns, ranges, and types before recommendation code runs, and FastAPI
returns a structured validation response.

Other endpoints:

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /dashboard`
- `GET /demo/{user_id}`

See [inference path](inference-path.md) and
[cold-start behavior](../experiments/cold-start.md).
