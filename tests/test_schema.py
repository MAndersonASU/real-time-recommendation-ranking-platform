import pandas as pd
import pytest

from recommender.data.schema import SchemaError, validate_behaviors

VALID_ROW = {
    "impression_id": 1,
    "user_id": "u1",
    "time": pd.Timestamp("2019-11-09T08:00:00"),
    "history": "n1 n2",
    "impressions": "n3-0 n1-1",
}


def _behaviors(**overrides) -> pd.DataFrame:
    row = {**VALID_ROW, **overrides}
    return pd.DataFrame([row])


def test_validate_behaviors_accepts_a_real_well_formed_row():
    validate_behaviors(_behaviors())  # must not raise


def test_validate_behaviors_accepts_a_row_with_no_history():
    validate_behaviors(_behaviors(history=None))  # must not raise


def test_validate_behaviors_rejects_an_impression_token_with_an_invalid_label():
    """Regression test for a real gap, found by audit: the original
    schema check only confirmed the impressions column was present and
    non-null, never that each token actually had the 'news_id-0' or
    'news_id-1' shape explode_impressions (recommender.data.mind)
    depends on. A label outside {0, 1} previously passed straight
    through to `.astype('int8')` as a nonsense click value instead of
    being rejected here, at the one place ingestion can still refuse it.
    """
    with pytest.raises(SchemaError):
        validate_behaviors(_behaviors(impressions="n3-0 n1-7"))


def test_validate_behaviors_rejects_an_impression_token_missing_a_label():
    with pytest.raises(SchemaError):
        validate_behaviors(_behaviors(impressions="n3-0 n1"))


def test_validate_behaviors_rejects_an_empty_impressions_field():
    with pytest.raises(SchemaError):
        validate_behaviors(_behaviors(impressions=""))


def test_validate_behaviors_rejects_a_malformed_history_entry():
    with pytest.raises(SchemaError):
        validate_behaviors(_behaviors(history="n1 n2-1"))
