# Structured application logs

Application logs are JSON objects written through Python's logging
system. Formatting helpers live in
`src/recommender/monitoring/structured_logging.py`.

## Request correlation

HTTP middleware creates a UUID for every request. The value is:

- stored on the request;
- included in application log records; and
- returned in the `X-Request-ID` response header.

A successful request produces a `request_completed` record. An
unhandled exception produces `request_failed` with the same ID and an
HTTP 500 response whose body does not contain the exception text.

The access record includes:

- event name;
- request ID;
- method;
- sanitized path;
- status code; and
- duration in milliseconds.

## Recommendation detail

A successful `/recommend` call also writes `recommend_served` with:

- requested and returned candidate counts;
- fallback status and reason;
- Redis degradation status; and
- durable and recent feature-use flags.

Quality tracking and this detail log run after the response has been
computed. If either observer fails, the completed recommendation is
still returned.

## User identifiers

The service does not write the raw recommendation user ID in its normal
application records. `hash_user_id()` stores the first 16 hexadecimal
characters of a SHA-256 digest so records for the same user can be
correlated.

The `/demo/{user_id}` route places the identifier in the URL. Access
logging replaces that path segment with the same digest, including the
trailing-slash redirect form. Fallback logging also uses the digest.

This is pseudonymization, not anonymity. Because the digest is
deterministic and unkeyed, someone who can guess the source identifiers
can test those guesses. Log access still needs normal security controls.

## JSON format

Every formatted application record includes:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "logger": "recommender.serving.app",
  "message": "request_completed"
}
```

Fields supplied through `extra` are added to the same object. Exception
records also contain `exc_info` for server-side diagnosis.

Tests verify unique request IDs, JSON parsing, identifier hashing,
sanitized demo paths, and correlation of failed requests.

See [operational metrics](operational-metrics.md) and
[security policy](../../SECURITY.md).
