# Recent-feature parity

This check compares two independent implementations of recent user
features:

- the in-memory `StreamConsumer`; and
- an offline recomputation from raw events.

Both receive the same user events and cutoff time. Kafka and Redis are
not part of this comparison.

Implementation: `src/recommender/features/parity.py`.

## Why an independent implementation, not a shared one

`compute_recent_features_offline` does not call streaming-consumer code.
It derives the fields directly from a raw event list. Reusing the online
implementation would make agreement automatic and would not detect
training-serving skew.

## What's compared, and how

For events at or before the cutoff, both paths produce:

- recent clicked items;
- impressions seen;
- clicks seen; and
- last event time.

The results are compared field by field.

## Verified against real data, at real cutoffs

`verify_parity.py` uses a real replay user with several distinct
impression times. Online and offline values matched at three historical
cutoffs:

| Cutoff | Clicks seen | Impressions seen |
|---|---:|---:|
| Early | 4 | 76 |
| Middle | 9 | 272 |
| Late | 12 | 387 |

Related infrastructure checks:

- [streaming consumer](../operations/streaming-consumer.md) for Kafka to
  consumer; and
- [live feature sync](live-feature-sync.md) for consumer to Redis.
