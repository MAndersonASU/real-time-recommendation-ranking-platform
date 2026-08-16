import pandas as pd
import pytest

from recommender.data.splits import assert_no_time_leakage, time_aware_split


def _behaviors(times):
    return pd.DataFrame(
        {
            "impression_id": range(len(times)),
            "user_id": ["U1"] * len(times),
            "time": pd.to_datetime(times),
            "history": [None] * len(times),
            "impressions": ["N1-1"] * len(times),
        }
    )


def test_time_aware_split_uses_last_day_as_validation():
    behaviors = _behaviors(
        [
            "2019-11-09 10:00:00",
            "2019-11-10 10:00:00",
            "2019-11-11 08:00:00",
            "2019-11-11 20:00:00",
        ]
    )

    train, validation = time_aware_split(behaviors, validation_days=1)

    assert list(train["time"].dt.date.astype(str)) == ["2019-11-09", "2019-11-10"]
    assert list(validation["time"].dt.date.astype(str)) == ["2019-11-11", "2019-11-11"]


def test_split_is_leakage_free():
    behaviors = _behaviors(["2019-11-09 10:00:00", "2019-11-10 10:00:00", "2019-11-11 10:00:00"])
    train, validation = time_aware_split(behaviors, validation_days=1)

    assert_no_time_leakage(train, validation)


def test_assert_no_time_leakage_catches_overlap():
    earlier = _behaviors(["2019-11-11 10:00:00"])
    later = _behaviors(["2019-11-10 10:00:00"])  # earlier than "earlier" — a real violation

    with pytest.raises(ValueError):
        assert_no_time_leakage(earlier, later)
