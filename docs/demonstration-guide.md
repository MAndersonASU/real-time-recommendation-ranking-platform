# Demonstration guide

The demonstration page traces one real recommendation request from
retrieval through ranking and explanation. It is not a mockup.

Open it after the API is running:

```bash
curl "http://localhost:8000/demo/U73700?num_candidates=3"
```

The implementation is in `src/recommender/serving/demo.py`.

## What the page shows

| Section | Source |
|---|---|
| Latency by service operation | The request's own `stage_timings` from `recommend()` |
| Retrieval history | The response's `retrieval_history_source` |
| Ranked results | The live response and the shared article catalog |
| Explanation | The matched signals returned for each item |

The page may report one of three retrieval sources:

- **Recent-history retrieval:** Redis contained usable clicks for the
  user.
- **Durable-history retrieval:** Redis did not contain usable clicks, so
  retrieval used the user's saved offline history.
- **Global-popularity retrieval:** neither source contained usable
  history.

The page reports ranking features separately. A request can use durable
features to score items even when retrieval used another source, so
combining the two labels would hide useful information.

Each ranked item includes its rank, real title, category, calibrated
score, and an evidence-based explanation when one is available. When
there is not enough evidence, the page says
`no explanation: insufficient evidence` instead of leaving the field
blank. See the [explanation boundary](experiments/explanation-boundary.md).

## Show recent-history retrieval

A new container usually has no live Redis record for a validation user.
Until a click arrives, the page correctly shows durable-history or
global-popularity retrieval.

For an end-to-end demonstration, start Kafka and the stream consumer,
then run:

```bash
python -m recommender.streaming.replay_producer
```

The next request for a user whose click was replayed will show
recent-history retrieval. See the
[replay producer guide](operations/replay-producer.md).

For a quick local demonstration without Kafka, write a record directly
to the same Redis instance used by the API:

  ```python
  from recommender.features.state_store import build_client, save_recent_features
  from recommender.features.online_features import RecentUserFeatures

  client = build_client()  # same default redis://localhost:6379/0 the API uses
  save_recent_features(
      client,
      RecentUserFeatures(
          user_id="U73700", recent_clicked_items=["N1", "N2"],
          impressions_seen=2, clicks_seen=2, last_event_time=None,
      ),
  )
  ```

After this write, `/demo/U73700` immediately shows
**Recent-history retrieval**. No API restart is required.

## Why the display matches the response

`build_demo_data()` calls `recommend()` once with
`include_matched_signals=True` and a `stage_timings` dictionary. Every
displayed value comes from that response. The page does not rerun or
recalculate the recommendation.

## Recorded live check

A live check against the rebuilt container used validation user
`U73700` while Redis contained no recent record.

| Observation | Result |
|---|---|
| Retrieval source | Durable-history retrieval |
| Ranking-feature status | Durable features used; recent Redis features unavailable |
| Total latency for this request | 36.81 ms |
| Retrieval latency for this request | 15.89 ms |
| Returned items | Three real catalog articles |
| Explanations | Content-similarity evidence for each item |

The 36.81 ms value is one request, not an aggregate. It is consistent
with the approximately 21.78 ms median in the
[serving latency report](experiments/serving-latency.md), because
individual requests vary.

This check also confirms the durable-history behavior recorded as
`SERVING-DURABLE-HISTORY-69`. Before that correction, this user would
have received global-popularity retrieval despite having saved history.
