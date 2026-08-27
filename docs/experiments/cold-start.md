# Cold Start

Gives every online-feature lookup an explicit, neutral fallback instead
of ever raising or serving a stale value, for users this system does not
yet know anything about. Implementation:
`src/recommender/features/cold_start.py`.

## Two independent kinds of "unknown"

A user can be missing from the durable feature dictionary
(`docs/operations/online-features.md`) — never seen in the offline training
history — without also being missing from Redis, and vice versa. A
long-time user's session state can simply have expired from Redis while
their durable history is intact; a brand-new user can already be
actively clicking before any offline batch job has ever run for them.
`get_online_features` looks up both sides independently and reports each
one's fallback status separately in the returned `OnlineFeatureLookup`,
rather than collapsing "unknown" into a single flag — a real user can
legitimately have zero lifetime clicks or an empty recent list, so
callers that need to tell a real zero from a fallback zero check
`durable_is_fallback` / `recent_is_fallback` directly instead of
guessing from the values.

## The defaults

`DEFAULT_DURABLE_FEATURES` (`dominant_category=None, lifetime_click_count=0`)
and `DEFAULT_RECENT_FEATURES` (`recent_clicked_items=[], impressions_seen=0,
clicks_seen=0, last_event_time=None`) are exactly the "no signal" values
the ranking features already expect — `dominant_category=None` is the
same sentinel `ranking/features.py`'s `dominant_category` function
returns for a user with no usable history, and `category_match` already
treats it as "no match" rather than crashing.

## Unseen items were already handled

Unseen items are also a cold-start concern, and this project already
covers them without any new code: `popularity.get(nid, 0)`
in `ranking/features.py` gives an item with no interaction history a
popularity of zero rather than raising, and the content-similarity path
skips any item missing from the TF-IDF vocabulary the same way. This
document's own contribution is specifically the user-level lookup — the one
gap that was still open.
