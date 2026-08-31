# Interaction event contract

The streaming pipeline converts MIND behavior rows into individual
interaction events. Kafka, the replay producer, and the consumer all use
the contract in `src/recommender/streaming/schema.py`.

## Event types

| Type | Meaning | Available from MIND |
|---|---|---|
| `impression` | An article was offered to a user | Yes |
| `click` | The user clicked an offered article | Yes |
| `skip` | The user did not click an offered article | Derived from `clicked=0` |
| `view` | The user saw or read an article without clicking | No |

The replay producer emits `impression`, `click`, and `skip` events. It
does not emit `view` because MIND has no dwell-time, scroll, or reading
signal.

## Required fields

| Field | Purpose |
|---|---|
| `event_id` | UUID for one interaction |
| `event_type` | One of the four event types |
| `schema_version` | Message format version |
| `user_id` | MIND user identifier |
| `item_id` | MIND article identifier |
| `impression_id` | Non-negative MIND impression identifier |
| `timestamp` | Time of the original interaction |
| `source` | Approved event origin |

`InteractionEvent` is an immutable dataclass. `to_json()` serializes it,
and `from_json()` rejects unknown or invalid fields before the message
reaches Redis or downstream logic.

User and article IDs may contain letters, numbers, periods, underscores,
colons, and hyphens. Each ID is limited to 128 characters.

## Time format

Historical replay keeps MIND's dataset-local timestamp, such as:

```text
2019-11-14 08:00:00
```

The dataset does not state a timezone, so the project does not invent
one. Any other approved source must use the project's strict,
timezone-aware RFC 3339 form, for example:

```text
2019-11-14T08:00:00Z
2019-11-14T08:00:00-05:00
```

The only approved sources are `mind_historical_replay` and
`synthetic_test`.

## Stable replay identity

`make_event()` uses `stable_event_id()` unless the caller provides an
ID. The function creates a UUID from the immutable event fields:
source, type, user, article, impression, and timestamp.

This makes replay repeatable: identical inputs produce the identical id
on every run and machine. The consumer can therefore recognize a
redelivery or repeated replay as a duplicate. A caller representing new
traffic may supply its own UUID.

## Compatibility rule

The current schema version is `1`. A consumer rejects a different
version instead of guessing how to interpret it. A schema change should
update the version, producer, consumer, tests, and this page together.

See [replay producer](replay-producer.md),
[streaming consumer](streaming-consumer.md), and
[recovery testing](recovery-testing.md).
