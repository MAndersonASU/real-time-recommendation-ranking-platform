# Cold-start behavior

An unknown user receives explicit neutral feature values. The caller can
tell those defaults from real zeros.

Implementation: `src/recommender/features/cold_start.py`.

## Durable and recent data are independent

A returning user may have durable offline history but no Redis record.
A new user may have live Redis clicks before the next offline build.

`get_online_features` looks up both stores independently.
`OnlineFeatureLookup` reports:

- `durable_is_fallback`;
- `recent_is_fallback`; and
- `redis_unavailable`.

These flags matter because a real user can legitimately have zero clicks
or an empty recent list.

## The defaults

| Default | Values |
|---|---|
| Durable | `dominant_category=None`, `lifetime_click_count=0`, `history_item_ids=()` |
| Recent | `recent_clicked_items=[]`, `impressions_seen=0`, `clicks_seen=0`, `last_event_time=None` |

These values mean “no signal.” `category_match` treats
`dominant_category=None` as no match. An empty durable history leads
retrieval to recent history when available, then global popularity.

## Unseen items were already handled

An article with no interaction history receives popularity zero through
`popularity.get(nid, 0)`. Content similarity skips an article missing
from its fitted catalog mapping instead of raising.

This page covers feature lookup defaults. The full retrieval hierarchy
is documented in [online features](../operations/online-features.md) and
[serving fallback](../operations/serving-fallback.md).
