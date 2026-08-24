# Structured Logging

Every log line is a real JSON object, correlated by a real per-request
ID, with the user identifier hashed rather than stored raw.
Implementation: `src/recommender/monitoring/structured_logging.py`,
wired into `src/recommender/serving/app.py`.

## Request IDs, for real traceability

A middleware generates a real UUID for every incoming request, stores
it on `request.state`, and echoes it back as a real `X-Request-ID`
response header. Every log line for that request — the access log at
the end, and `recommend_served`'s own detail line — carries the same
id. Given one id from a client bug report or an alert, every log line
for that specific request can be found directly, not guessed at by
timestamp.

This holds for unhandled exceptions too, not just successful requests.
The middleware wraps the downstream call in `try`/`except`: on an
unhandled exception it still logs a `request_failed` line carrying the
same request id, and still sets the `X-Request-ID` header on the 500
response it returns — a caller reporting a failed request can always
be traced to its server-side log line, and the response body never
leaks the underlying exception's own text.

## Sanitization: hashed, not raw, user identifiers

`recommend_served` logs `user_id_hash`, never the real `user_id`. MIND's
ids are already synthetic, not real names, but logging the raw value
repeatedly across every request would still let anyone with log access
reconstruct one user's entire request history verbatim. A truncated
SHA-256 (`hash_user_id`) gives an operator exactly what debugging
actually needs — "these log lines are the same user" — without ever
writing the reversible, raw identifier to a log file. Deterministic on
purpose (the same input always hashes the same way), so correlation
across many log lines still works.

The fallback path (`safe_recommend`, `src/recommender/serving/fallback.py`)
uses the same `hash_user_id` helper when it logs the reason a request
fell back to popularity ranking — it previously logged the raw
`user_id` directly on that path, inconsistent with the primary
`recommend_served` line above. `tests/test_serving_fallback.py::
test_safe_recommend_never_logs_the_raw_user_id` asserts the raw value
never appears in that log record.

## Real JSON, not a formatted string

`JsonFormatter` builds one JSON object per log line directly from the
standard library's own `logging` mechanism — everything passed via
`extra={...}` at the call site becomes a real field in the object, with
no per-call-site formatting logic to keep in sync. Any log aggregator
can parse this directly; a hand-formatted f-string log line can't be
queried the same way.

## Verified against the real running container

A real request against the rebuilt container produced two real,
correlated JSON log lines sharing the identical request id, with the
logged `user_id_hash` genuinely different from — and non-reversible to
— the real `user_id` sent in the request, and the same id came back on
the response's `X-Request-ID` header.
