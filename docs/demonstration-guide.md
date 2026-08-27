# Demonstration guide

`GET /demo/{user_id}` on the real, already-running recommendation
service — one real request traced end to end, not a mockup or a set
of curated screenshots. Implementation:
`src/recommender/serving/demo.py`.

## What the page shows

- **Per-stage latency** — the same six-stage breakdown
  `docs/serving-latency.md` already measures, read directly from
  `recommend()`'s own `stage_timings` for this specific request.
- **Personalization status** — the real `durable_features_used` /
  `recent_features_used` flags on the response, labeled plainly as
  fully personalized, partially personalized, or cold start.
- **The ranked slate** — rank, real title (looked up from the same
 catalog every component uses), category, and calibrated score.
- **A real explanation per item** — the optional explanation layer
  (`docs/explanation-boundary.md`) called live against this request's
  real matched signals, showing an honest "no explanation: insufficient
  evidence" line rather than a blank space when there's genuinely
  nothing to cite.

## One real pipeline call, nothing recomputed for display

`build_demo_data()` calls `recommend()` exactly once, with
`include_matched_signals=True` and a real `stage_timings` dict, and
derives every value the page shows from that single response. A
version that ran the pipeline once for the numbers and separately
re-derived anything for the page would risk the two silently
disagreeing — this can't, since there's only one call.

## Runtime verification

```bash
curl "http://localhost:8000/demo/U73700?num_candidates=3"
```

Against the real rebuilt container, alongside real Kafka and Redis:
returned a real page for real validation-split user `U73700` —
"Partially personalized," total latency 11.24ms (consistent with the
~12.79ms p50 already measured in `docs/serving-latency.md`), a real
per-stage breakdown (reranking the largest single cost at 4.58ms, the
same finding as that earlier measurement), three real catalog
articles with their real titles, and a real explanation for each item
("Recommended because it matches your interest in lifestyle.") — the
same template-fallback behavior `docs/explanation-generation.md`
already found to be the common case for this small local model.
