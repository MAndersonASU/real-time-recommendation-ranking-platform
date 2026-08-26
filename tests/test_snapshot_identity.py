"""A snapshot id has to identify the snapshot.

The previous implementation summed `hash(user_id)` over the user set and
documented itself as stable across processes and derived from content.
It was neither. Python randomises `str` hashing per process (PEP 456), so
identical data produced a different id on every restart; and because only
the user *set* was hashed, changing every feature value left the id
untouched.

These tests pin both properties. The cross-process one runs real
subprocesses under different `PYTHONHASHSEED` values, because a
same-process test cannot observe hash randomisation at all -- the seed is
fixed once at interpreter start, so the defect was invisible to every
in-process assertion.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime

from recommender.features.online_features import DurableUserFeatures
from recommender.serving.cache import DurableFeatureCache

DATA_AS_OF = datetime(2019, 11, 14, 23, 59, 13, tzinfo=UTC)


def _cache(features, data_as_of=DATA_AS_OF):
    return DurableFeatureCache(
        features_by_user={f.user_id: f for f in features},
        built_at=datetime.now(UTC),
        data_as_of=data_as_of,
    )


def _users(n=5, clicks=3, category="sports"):
    return [DurableUserFeatures(f"U{i}", category, clicks + i) for i in range(n)]


def test_the_same_snapshot_gives_the_same_id():
    assert _cache(_users()).snapshot_id() == _cache(_users()).snapshot_id()


def test_build_time_does_not_change_the_id():
    """`built_at` moves on every restart. If it reached the id, the id
    would report a change that never happened to the data.
    """
    early = DurableFeatureCache(
        features_by_user={f.user_id: f for f in _users()},
        built_at=datetime(2020, 1, 1, tzinfo=UTC),
        data_as_of=DATA_AS_OF,
    )
    late = DurableFeatureCache(
        features_by_user={f.user_id: f for f in _users()},
        built_at=datetime(2026, 8, 25, tzinfo=UTC),
        data_as_of=DATA_AS_OF,
    )

    assert early.snapshot_id() == late.snapshot_id()


def test_insertion_order_does_not_change_the_id():
    """Dict order follows the order rows arrived from the split file,
    which is not part of the snapshot's identity.
    """
    forward = _users()
    assert _cache(forward).snapshot_id() == _cache(list(reversed(forward))).snapshot_id()


def test_changing_a_feature_value_changes_the_id():
    """The defect that mattered most. Same users, same `data_as_of`,
    different feature values -- serving behaviour changes while the
    reported version would have stayed identical.
    """
    before = _cache(_users(clicks=3))
    after = _cache(_users(clicks=99))

    assert before.snapshot_id() != after.snapshot_id()


def test_changing_a_dominant_category_changes_the_id():
    assert _cache(_users(category="sports")).snapshot_id() != _cache(
        _users(category="finance")
    ).snapshot_id()


def test_adding_a_user_changes_the_id():
    assert _cache(_users(n=5)).snapshot_id() != _cache(_users(n=6)).snapshot_id()


def test_changing_the_data_date_changes_the_id():
    assert _cache(_users()).snapshot_id() != _cache(
        _users(), data_as_of=datetime(2019, 11, 15, tzinfo=UTC)
    ).snapshot_id()


def test_field_boundaries_are_unambiguous():
    """Without separators, ("ab", "c") and ("a", "bc") hash identically.
    Two users whose fields concatenate to the same bytes must not
    collide.
    """
    a = _cache([DurableUserFeatures("U1", "ab", 1), DurableUserFeatures("U2", "c", 1)])
    b = _cache([DurableUserFeatures("U1", "a", 1), DurableUserFeatures("U2", "bc", 1)])

    assert a.snapshot_id() != b.snapshot_id()


_SUBPROCESS_SNIPPET = """
import sys
from datetime import UTC, datetime
from recommender.features.online_features import DurableUserFeatures
from recommender.serving.cache import DurableFeatureCache

features = [DurableUserFeatures(f"U{i}", "sports", 3 + i) for i in range(5)]
cache = DurableFeatureCache(
    features_by_user={f.user_id: f for f in features},
    built_at=datetime.now(UTC),
    data_as_of=datetime(2019, 11, 14, 23, 59, 13, tzinfo=UTC),
)
sys.stdout.write(cache.snapshot_id())
"""


def _id_under_hash_seed(seed: str) -> str:
    # The real environment plus an overridden seed. Building a bare env
    # from scratch breaks the interpreter on Windows, which needs PATH
    # and SYSTEMROOT to start at all.
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SNIPPET],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def test_the_id_is_identical_across_processes_with_different_hash_seeds():
    """The regression test proper.

    Under the old implementation these two subprocesses returned
    different ids from identical data, because `PYTHONHASHSEED` changes
    what `hash("U0")` returns. Any in-process test would have passed.
    """
    first = _id_under_hash_seed("0")
    second = _id_under_hash_seed("12345")
    third = _id_under_hash_seed("99999")

    assert first, "subprocess produced no snapshot id"
    assert first == second == third, (
        f"snapshot id varies with PYTHONHASHSEED: {first}, {second}, {third}"
    )


def test_the_id_matches_the_one_computed_in_this_process():
    """Cross-process agreement is only useful if it also agrees with the
    value this process would publish.
    """
    assert _id_under_hash_seed("777") == _cache(_users()).snapshot_id()
