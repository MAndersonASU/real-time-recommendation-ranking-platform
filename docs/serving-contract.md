# Serving Contract

Typed request/response schemas for the online recommendation service,
defined before any of the actual inference wiring (retrieval → ranking →
reranking → response) is built. Implementation:
`src/recommender/serving/contract.py`.

## Why schemas come before the endpoint

A request and response shape decided while writing the endpoint tends to
follow whatever the code happens to produce, rather than what a caller
actually needs. Defining `RecommendationRequest`, `RecommendedItem`, and
`RecommendationResponse` first, with real validation, forces every field
and its constraints to be decided deliberately and gives the later
integration step (`docs/inference-path.md`, once written) a fixed target
to build toward instead of a moving one.

## Pydantic, not a plain dataclass

`recommender.features.online_features` uses plain dataclasses, since
those types only ever flow between trusted, internal Python code. A
serving contract is different: it describes the shape of data crossing a
real network boundary, arriving as untrusted JSON from a caller who might
send a negative candidate count or an empty user id. Pydantic validates
that shape at the boundary and raises a clear, structured error before any
of that bad input reaches real logic — which is exactly why FastAPI (the
framework `docs/inference-path.md` will use once the endpoint itself is
built) is built around it rather than a general-purpose framework.

## What's actually constrained, and why

- `RecommendationRequest.num_candidates` is capped at 50 and must be
  positive — an unbounded request could ask for the entire catalog,
  which is a real cost/latency risk this contract closes off at the door
  rather than downstream.
- `RecommendedItem.score` is constrained to `[0, 1]` because the ranking
  model (`docs/ranking-model.md`) is a calibrated logistic regression
  probability, not an unbounded raw score. A score outside that range
  would mean something upstream is already broken, not a valid case a
  caller has to handle.
- `RecommendationResponse.durable_features_used` /
  `recent_features_used` surface Phase 7's cold-start fallback signal
  (`OnlineFeatureLookup.durable_is_fallback` / `recent_is_fallback`,
  `docs/cold-start.md`) directly in the response, inverted to read from
  the caller's point of view — so a heavily-fallback recommendation
  never looks identical to a fully personalized one.
