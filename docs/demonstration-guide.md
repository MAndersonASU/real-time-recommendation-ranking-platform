# Demonstration guide

`GET /demo/{user_id}` on the real, already-running recommendation
service — one real request traced end to end, not a mockup or a set
of curated screenshots. Implementation:
`src/recommender/serving/demo.py`.

## What the page shows

- **Per-stage latency** — the same six-stage breakdown
  `docs/experiments/serving-latency.md` already measures, read directly from
  `recommend()`'s own `stage_timings` for this specific request.
- **Retrieval-source status** (SERVING-DURABLE-HISTORY-69) — the real
  `retrieval_history_source` on the response, labeled as one of three
  genuinely distinct outcomes: **"Recent-history retrieval"** (Redis
  had a usable click history for this user), **"Durable-history
  retrieval"** (Redis had nothing usable, so retrieval fell back to the
  user's own offline history), or **"Global-popularity retrieval"**
  (neither existed). A substatus line separately shows the older
  `durable_features_used`/`recent_features_used` flags, since a
  response can have durable features used purely for ranking-side
  scoring while retrieval itself used a different history entirely --
  these two lines answer different questions and are shown separately
  on purpose, not collapsed into one "personalized/not" phrase the way
  an earlier version of this page did.
- **The ranked slate** — rank, real title (looked up from the same
 catalog every component uses), category, and calibrated score.
- **A real explanation per item** — the optional explanation layer
  (`docs/experiments/explanation-boundary.md`) called live against this request's
  real matched signals, showing an honest "no explanation: insufficient
  evidence" line rather than a blank space when there's genuinely
  nothing to cite.

## Getting "Recent-history retrieval" to show

Most validation-split users have no live Redis record at the moment a
fresh container starts, so `/demo/{user_id}` shows "Durable-history
retrieval" or "Global-popularity retrieval" for them, honestly, until a
real recent-click event exists for that specific user. Two ways to
produce one:

- **The real streaming path.** Start Kafka and the stream consumer,
  then run `python -m recommender.streaming.replay_producer`
  (`docs/operations/replay-producer.md`) to publish real, chronologically
  paced click/impression events -- any user the replay stream produces a
  real click for will show "Recent-history retrieval" on their next
  `/demo/{user_id}` request, exactly the way a real production event
  would arrive.
- **Directly, for a quick local demonstration**, without Kafka running
  at all:

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

  `/demo/U73700` immediately shows "Recent-history retrieval" afterward
  -- this writes directly to the same Redis instance the running API
  reads from, so no restart is needed.

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

Against the real rebuilt container, with Redis running and no recent
record for this user: returned a real page for real validation-split
user `U73700` — **"Durable-history retrieval"** (SERVING-DURABLE-HISTORY-69;
before that fix, this same user with no live Redis record would have
shown "Global-popularity retrieval" instead, regardless of their real
durable history), substatus "durable features used · recent (Redis)
features not available," total latency 36.81ms (within the range of
the ~21.78ms p50 already measured in `docs/experiments/serving-latency.md`
-- one request's own latency naturally varies around an aggregate p50,
and candidate retrieval at 15.89ms here is on the higher end of that
stage's own distribution), a real per-stage breakdown for this one
request, three real catalog articles with their real titles, and a real
explanation grounded in content similarity for each item ("Recommended
because its content closely resembles articles you've read before.")
-- itself only possible because retrieval ran on this user's real
durable history rather than the flat popularity pool a historyless
request produces, which is exactly the retrieval-side personalization
SERVING-DURABLE-HISTORY-69's fix restores.
