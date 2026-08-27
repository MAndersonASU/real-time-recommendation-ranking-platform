# Event Schema

The streaming pipeline turns MIND's behavior logs from a finished table into a stream of
individual interaction events — what a real system would receive one at a
time, in order, as it happens. This check defines the message format all
the streaming components (Kafka broker, replay producer, streaming
consumer) shares. Implementation: `src/recommender/streaming/schema.py`.

## Four event types, and an honest gap

| Type | Meaning | MIND support |
|---|---|---|
| `impression` | An item was shown to a user as a candidate | Direct — every exploded impression row |
| `click` | The user clicked a shown item | Direct — the `clicked=1` flag |
| `skip` | The user was shown an item and didn't click it | Derived — `clicked=0` on an impression row |
| `view` | The item was seen/dwelled on, short of a click | Not available at all |

All four are defined because a real event schema should describe every
interaction a production system might one day emit, not only the ones one
dataset happens to support. But the gap is real and disclosed rather than
implied away: MIND has no signal for "the user actually looked at this"
separate from "the user clicked it" — no dwell time, no scroll depth,
nothing. The replay producer (`docs/operations/replay-producer.md`) only ever emits `impression`,
`click`, and the derived `skip`. `view` stays in the schema as a defined,
unpopulated type — the same disclosed-limitation pattern already applied
to article freshness in the ranking model and reranking.

## Fields on every event

- **`event_id`** — a globally unique identifier for this specific event,
  what the recovery testing's duplicate detection checks against (`docs/operations/recovery-testing.md`), not the impression
  or item id.
- **`event_type`** — one of the four types above.
- **`schema_version`** — which version of this event format the message
  conforms to, so a future consumer can detect a layout change rather than
  silently misreading an old or new message.
- **`user_id`, `item_id`, `impression_id`** — carried directly from MIND's
  own identifiers, no new ID scheme invented where a real one exists.
- **`timestamp`** — when the interaction happened: the original MIND
  impression time during replay, not the time the message happens to be
  produced.
- **`source`** — where the event actually came from. Defaults to a literal
  value naming historical replay, not a live feed, keeping the schema
  itself honest about what this system is — matching the frozen research
  scope's own "replayed-stream, not live production" boundary.

`InteractionEvent` is a frozen dataclass with `to_json`/`from_json` for
Kafka message (de)serialization. By default, `make_event` assigns
`event_id` a **deterministic** id (`stable_event_id`, a `uuid5` derived
from this event's own immutable fields — type, user, item, impression,
timestamp, source): identical inputs produce the identical id, on any
run, on any machine. That is deliberate, not incidental — replay is
re-runnable by design, and a random id would make the same historical
event look brand new every time it replayed, defeating the duplicate
detection this schema exists to support
(`docs/operations/streaming-consumer.md`). A caller representing
genuinely new, live traffic can pass its own `event_id` instead of
relying on the default. Verified with 3 tests: a JSON round-trip
preserves every field including the event-type enum (not a bare
string); identical inputs produce the identical id; ids differ when any
identifying field differs.
