import hashlib
import json
import logging
import time
import uuid

USER_ID_HASH_LENGTH = 16


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per log line, not a hand-formatted string --
    real structured logging, parseable by any log aggregator, rather
    than text meant only for a human scrolling a terminal. Every field
    beyond the standard ones comes from `extra=` at the call site
    (`logging`'s own mechanism for this), so this formatter never has to
    know what any particular log line is about.
    """

    RESERVED_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_structured_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def new_request_id() -> str:
    return str(uuid.uuid4())


def hash_user_id(user_id: str) -> str:
    """A one-way, truncated fingerprint of a user id -- enough for an
    operator to see "this is the same user across these log lines"
    while debugging, without the raw identifier ever sitting in a log
    file. MIND user ids are already synthetic, not real names, but
    logging them directly and repeatedly would still let anyone reading
    the logs reconstruct one user's full request history verbatim; this
    doesn't need to be reversible to be useful for correlation, so it
    deliberately isn't.
    """
    return hashlib.sha256(user_id.encode()).hexdigest()[:USER_ID_HASH_LENGTH]


def now_ms() -> float:
    return time.perf_counter() * 1000
