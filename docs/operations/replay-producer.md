# Replay Producer

Publishes the `replay` split (`docs/experiments/splits.md` — MIND's
official dev day) to Kafka, in the exact chronological order the
interactions actually happened, paced by a real-time-scaled sleep
rather than sent as one batch. Implementation: `src/recommender/streaming/replay_producer.py`.

## Why paced replay, not a batch load

Every other split has been loaded as a finished table and queried however
was convenient. That's fine for offline evaluation, but it's the opposite
of how a real system experiences data — one event at a time, with real
gaps of silence in between. Loading `replay` as a single batch would let
a consumer buffer and process everything instantly, which would make the
recovery testing that follows this check meaningless — there'd be no
"mid-stream" for a consumer to actually crash during.

The producer walks `replay`'s 73,152 impressions in true chronological
order and sleeps between rows in proportion to the gap between their
original timestamps, scaled down by a speed multiplier (default 3,600× —
one real second per simulated hour, compressing the full day into about
24 real seconds of waiting) while every event still arrives in true
relative order and spacing.

Each candidate produces two events, not one: an `impression`, always,
plus either a `click` or a derived `skip` (`docs/operations/event-schema.md`). MIND
records no separate click timestamp relative to the impression, so both
events honestly share the impression's own time rather than inventing a
plausible-looking delay that isn't real data.

## Results

2,000 chronologically-first rows from `replay`, speed 7,200× (roughly 2
simulated hours per real second):

| | |
|---|---|
| Rows replayed | 2,000 |
| Events sent | 4,000 |
| Impressions sent | 2,000 |
| Clicks sent | 87 |
| Skips sent | 1,913 |
| Delivery errors | 0 |
| Wall-clock seconds | 0.22 |

87/2,000 = 4.35% click rate — consistent with the ~4% overall CTR already
measured for this dataset (`docs/experiments/data-quality.md`), a real cross-check
that the replayed sample isn't behaving anomalously. Zero delivery
errors, confirming every event actually reached the broker. Reproducible
via `python -m recommender.streaming.replay_producer` with a broker
running (`docs/operations/kafka-local.md`).
