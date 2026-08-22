import pandas as pd

from recommender.evaluation.failure_analysis import (
    HISTORY_LENGTH_BINS,
    HISTORY_LENGTH_LABELS,
    _segment_miss_rate,
)


def test_segment_miss_rate_counts_misses_within_the_masked_subset():
    frame = pd.DataFrame({"hit": [True, False, False, True]})
    mask = pd.Series([True, True, False, False])

    result = _segment_miss_rate(frame, mask)

    assert result["n"] == 2
    assert result["miss_rate"] == 0.5  # one hit, one miss in the masked subset


def test_segment_miss_rate_is_none_for_an_empty_segment():
    frame = pd.DataFrame({"hit": [True, False]})
    mask = pd.Series([False, False])

    result = _segment_miss_rate(frame, mask)

    assert result["n"] == 0
    assert result["miss_rate"] is None


def test_history_length_buckets_place_zero_history_in_its_own_bucket():
    lengths = pd.Series([0, 3, 15, 40])

    buckets = pd.cut(lengths, bins=HISTORY_LENGTH_BINS, labels=HISTORY_LENGTH_LABELS)

    assert list(buckets.astype(str)) == ["0", "1-5", "6-20", "20+"]
