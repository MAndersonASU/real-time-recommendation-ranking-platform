from datetime import datetime, timedelta

import pandas as pd

from recommender.serving.cache import DurableFeatureCache, build_durable_feature_cache, refresh

NEWS = pd.DataFrame({"news_id": ["n1", "n2"], "category": ["sports", "tech"]})
BEHAVIORS = pd.DataFrame(
    {
        "user_id": ["u1"],
        "time": pd.to_datetime(["2019-11-10T08:00:00"]),
        "history": ["n1"],
    }
)


def test_freshly_built_cache_is_not_stale():
    cache = build_durable_feature_cache(BEHAVIORS, NEWS)

    assert cache.is_stale() is False


def test_cache_reports_stale_past_its_named_max_age():
    now = datetime(2019, 11, 15, 12, 0, 0)  # noqa: DTZ001 -- naive, matches every other timestamp in this project
    cache = DurableFeatureCache(features_by_user={}, computed_at=now, max_age_seconds=60.0)

    assert cache.is_stale(now=now + timedelta(seconds=61)) is True
    assert cache.is_stale(now=now + timedelta(seconds=30)) is False


def test_get_returns_none_for_a_user_not_in_the_cache():
    cache = build_durable_feature_cache(BEHAVIORS, NEWS)

    assert cache.get("nobody-in-this-cache") is None


def test_refresh_returns_a_new_cache_with_a_later_timestamp_and_does_not_mutate_the_old_one():
    original = build_durable_feature_cache(BEHAVIORS, NEWS)
    more_behaviors = pd.concat(
        [
            BEHAVIORS,
            pd.DataFrame(
                {"user_id": ["u2"], "time": pd.to_datetime(["2019-11-10T09:00:00"]), "history": ["n2"]}
            ),
        ],
        ignore_index=True,
    )

    refreshed = refresh(original, more_behaviors, NEWS)

    assert refreshed.computed_at >= original.computed_at
    assert "u2" in refreshed.features_by_user
    assert "u2" not in original.features_by_user
