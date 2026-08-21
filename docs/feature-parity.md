# Feature Parity

Checks that the online feature path (Kafka → streaming consumer → Redis)
and an independently written offline recomputation produce exactly the
same recent-feature values, given the same user and the same historical
cutoff. Implementation: `src/recommender/features/parity.py`.

## Why an independent implementation, not a shared one

`compute_recent_features_offline` deliberately does not call anything in
`recommender.streaming.consumer`. It re-derives recent-clicked-items,
impression and click counts, and last-event-time directly from a raw
event list using plain Python. The point of a parity check is confirming
two *separately written* implementations of the same feature definition
agree — reusing the online code here would make the test pass by
construction and prove nothing about whether the online path is actually
correct. This is what the field calls a training-serving skew check:
the online (serving) computation and the offline (training-time)
computation of the same feature must never quietly diverge.

## What's compared, and how

Given a raw list of `InteractionEvent`s and a cutoff timestamp,
`compute_recent_features_offline` filters to one user's events at or
before that cutoff, sorts them, and derives the same four fields
`RecentUserFeatures` defines. Separately, a real `StreamConsumer`
processes the identical events, in the same chronological order, up to
the same cutoff — and the resulting state is compared field for field
against the offline result.

## Verified against real data, at real cutoffs

`verify_parity.py` runs this against a real user from the reserved
`replay` split (`docs/splits.md`), picked specifically for having several
genuinely distinct impression times (not just many candidate rows within
one session, which all share a single timestamp). At three different
real cutoffs for that user — early, middle, and late in their real
history — the online and offline computations matched exactly, with
click and impression counts growing correctly as the cutoff advances
(4/76 → 9/272 → 12/387 clicks/impressions seen for the user checked).
