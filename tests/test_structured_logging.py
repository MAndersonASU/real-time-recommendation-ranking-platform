import json
import logging

from recommender.monitoring.structured_logging import JsonFormatter, hash_user_id, new_request_id


def _log_and_format(**extra) -> dict:
    logger = logging.getLogger("test.structured")
    record = logger.makeRecord(
        "test.structured", logging.INFO, __file__, 1, "something happened", (), None, extra=extra
    )
    return json.loads(JsonFormatter().format(record))


def test_format_produces_valid_json_with_the_real_message():
    payload = _log_and_format()

    assert payload["message"] == "something happened"
    assert payload["level"] == "INFO"


def test_format_includes_every_extra_field_passed_at_the_call_site():
    payload = _log_and_format(request_id="abc-123", user_id_hash="deadbeef")

    assert payload["request_id"] == "abc-123"
    assert payload["user_id_hash"] == "deadbeef"


def test_hash_user_id_never_contains_the_raw_id():
    raw_id = "U10103"

    hashed = hash_user_id(raw_id)

    assert raw_id not in hashed
    assert hashed != raw_id


def test_hash_user_id_is_deterministic_for_correlation():
    assert hash_user_id("U10103") == hash_user_id("U10103")


def test_hash_user_id_differs_for_different_users():
    assert hash_user_id("U10103") != hash_user_id("U99999")


def test_new_request_id_is_unique_each_call():
    assert new_request_id() != new_request_id()
