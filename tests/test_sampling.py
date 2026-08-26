import pandas as pd
import pytest

from recommender.evaluation.sampling import (
    DEFAULT_SAMPLE_SEED,
    describe_sample,
    sample_impression_ids,
)


@pytest.fixture
def impressions():
    """Two properties matter for the tests below and are built in
    deliberately: impressions are ordered in time, and users are
    correlated with time -- early users appear only early. That is what
    makes a `head(N)` selection unrepresentative rather than merely
    arbitrary, and it mirrors the real split, where a user's session sits
    in one part of the day.
    """
    rows = []
    for i in range(200):
        rows.append(
            {
                "impression_id": f"i{i:03d}",
                "user_id": f"U{i // 20}",
                "time": pd.Timestamp("2019-11-14") + pd.Timedelta(minutes=i),
            }
        )
    return pd.DataFrame(rows)


def test_the_same_seed_selects_the_same_impressions(impressions):
    first = sample_impression_ids(impressions, 30)
    second = sample_impression_ids(impressions, 30)

    assert list(first) == list(second)


def test_a_different_seed_selects_a_different_sample(impressions):
    default = sample_impression_ids(impressions, 30)
    other = sample_impression_ids(impressions, 30, seed=DEFAULT_SAMPLE_SEED + 1)

    assert list(default) != list(other), (
        "the seed must actually drive the draw, or 'seeded' is decoration"
    )


def test_the_sample_spans_the_whole_window_not_just_its_start(impressions):
    """The defect this replaces: `head(30)` returned the first 30
    impressions, so every comparison drawn from it described the first
    half hour and the first two users only.
    """
    selected = sample_impression_ids(impressions, 30)
    sampled = impressions[impressions["impression_id"].isin(selected)]

    head = impressions.head(30)
    assert sampled["user_id"].nunique() > head["user_id"].nunique()
    assert sampled["time"].max() > head["time"].max()
    # Reaches the far end of the window, which a prefix by construction
    # never can.
    assert sampled["time"].max() > impressions["time"].quantile(0.9)


def test_asking_for_more_than_exists_returns_everything(impressions):
    selected = sample_impression_ids(impressions, 10_000)

    assert len(selected) == len(impressions)
    assert list(selected) == sorted(impressions["impression_id"])


def test_selection_is_returned_in_a_stable_order(impressions):
    selected = sample_impression_ids(impressions, 25)

    assert list(selected) == sorted(selected)


def test_duplicate_rows_for_one_impression_are_selected_once(impressions):
    """Feature tables carry one row per candidate, so an impression id
    appears many times. Sampling must draw impressions, not rows.
    """
    exploded = pd.concat([impressions] * 4, ignore_index=True)

    selected = sample_impression_ids(exploded, 30)

    assert len(selected) == 30
    assert len(set(selected)) == 30


def test_the_description_records_what_a_reader_needs_to_interpret_it(impressions):
    selected = sample_impression_ids(impressions, 40)

    description = describe_sample(impressions, selected)

    assert description["seed"] == DEFAULT_SAMPLE_SEED
    assert description["eligible_impressions"] == 200
    assert description["selected_impressions"] == 40
    assert description["selected_fraction"] == pytest.approx(0.2)
    assert description["distinct_users"] > 1
    assert description["time_range"]["start"] < description["time_range"]["end"]


def test_the_description_fingerprints_the_selection_without_publishing_it(impressions):
    """The digest lets a later run confirm it drew the same sample. The
    ids themselves stay out of the report: they are dataset content, and
    the dataset is licensed.
    """
    selected = sample_impression_ids(impressions, 40)
    other = sample_impression_ids(impressions, 40, seed=DEFAULT_SAMPLE_SEED + 1)

    description = describe_sample(impressions, selected)

    assert description["selected_ids_sha256"] != describe_sample(
        impressions, other, seed=DEFAULT_SAMPLE_SEED + 1
    )["selected_ids_sha256"]
    assert "i000" not in str(description)


def test_the_selection_digest_is_a_full_sha256(impressions):
    """Named `sha256`, so it has to be one.

    An earlier version stored `hexdigest()[:16]` -- a 64-bit prefix --
    under a field name promising a full digest, while the same report
    format insisted on complete hashes for every fit-only artifact. The
    inconsistency mattered more than the collision risk.
    """
    import re

    description = describe_sample(impressions, sample_impression_ids(impressions, 20))

    digest = description["selected_ids_sha256"]
    assert len(digest) == 64, f"digest is {len(digest)} characters, not a full SHA-256"
    assert re.fullmatch(r"[0-9a-f]{64}", digest), "digest must be lowercase hexadecimal"
