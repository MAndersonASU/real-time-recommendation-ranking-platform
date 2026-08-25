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


def test_a_freshly_built_snapshot_over_old_data_is_still_reported_stale():
    """Regression test for a misleading signal: staleness was measured
    against the time the process built the snapshot, so restarting the
    service relabelled a frozen 2019 dataset as freshly computed.

    Staleness is now measured against `data_as_of` -- the newest event in
    the underlying data -- which restarting does not change. Building
    this cache right now over 2019 behaviours must therefore report
    stale.
    """
    cache = build_durable_feature_cache(BEHAVIORS, NEWS)

    assert cache.is_stale() is True
    assert cache.built_at.year >= 2026  # built now
    assert cache.data_as_of.year == 2019  # data are not


def test_built_at_and_data_as_of_are_reported_separately():
    cache = build_durable_feature_cache(BEHAVIORS, NEWS)

    described = cache.describe()

    assert described["data_as_of"].startswith("2019-11-10")
    assert described["built_at"] != described["data_as_of"]
    assert described["data_age_seconds"] > 0
    # The metadata must not imply a refresh pipeline that does not exist.
    assert "not refreshed" in described["refresh_policy"]


def test_snapshot_id_is_stable_across_rebuilds_of_the_same_data():
    """A restart rebuilds the snapshot but does not change which
    snapshot it is, so the identifier must not move.
    """
    first = build_durable_feature_cache(BEHAVIORS, NEWS)
    second = build_durable_feature_cache(BEHAVIORS, NEWS)

    assert first.snapshot_id() == second.snapshot_id()
    # built_at is deliberately not compared: it may or may not differ
    # depending on clock resolution, and the point is that the
    # snapshot identity does not depend on it either way.


def test_snapshot_id_changes_when_the_underlying_data_change():
    newer = pd.DataFrame(
        {
            "user_id": ["u1", "u2"],
            "time": pd.to_datetime(["2019-11-10T08:00:00", "2019-11-11T08:00:00"]),
            "history": ["n1", "n2"],
        }
    )

    assert (
        build_durable_feature_cache(BEHAVIORS, NEWS).snapshot_id()
        != build_durable_feature_cache(newer, NEWS).snapshot_id()
    )


def test_cache_reports_stale_past_its_named_max_age():
    now = datetime(2019, 11, 15, 12, 0, 0)  # noqa: DTZ001 -- naive, matches every other timestamp in this project
    cache = DurableFeatureCache(features_by_user={}, built_at=now, data_as_of=now, max_age_seconds=60.0)

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

    assert refreshed.built_at >= original.built_at
    assert "u2" in refreshed.features_by_user
    assert "u2" not in original.features_by_user
