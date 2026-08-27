"""Bounded, per-user evaluations must use a real, described sample.

`evaluate_explanations` and `verify_latency_by_stage` used to take the
first N distinct users the validation split happened to list --
`unique()[:num_users]` and `drop_duplicates().head(num_users)` -- while
their published reports asserted the opposite under
`recommender.evaluation.publish.FULL_POPULATION`: "no sampling -- every
eligible impression in the split was evaluated." Neither claim was
true, and nothing enforced that it had to be.

These tests cover the two things that make that impossible now:

1. `sample_user_ids` / `describe_user_sample` actually draw a seeded,
   reproducible, non-prefix sample and describe it honestly.
2. `publish_explanation_report` and `publish_serving_latency_report` no
   longer default `sampling` to `FULL_POPULATION` -- a caller that omits
   it fails immediately, before any report is built, rather than
   silently publishing a false claim.
"""

import inspect

import pandas as pd
import pytest

from recommender.evaluation.publish import (
    publish_explanation_report,
    publish_serving_latency_report,
)
from recommender.evaluation.sampling import (
    DEFAULT_SAMPLE_SEED,
    describe_user_sample,
    sample_user_ids,
)


@pytest.fixture
def users_frame() -> pd.DataFrame:
    """200 distinct users, each with a real, spread-out timestamp --
    large enough that a prefix-vs-sample difference is detectable.
    """
    return pd.DataFrame(
        {
            "user_id": [f"U{i}" for i in range(200)],
            "time": pd.date_range("2019-11-09", periods=200, freq="h"),
        }
    )


def test_sample_user_ids_is_not_a_prefix(users_frame: pd.DataFrame) -> None:
    """The sample must not just be the first N ids in frame order."""
    selected = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED)
    prefix = list(users_frame["user_id"].iloc[:20])
    assert list(selected) != prefix


def test_sample_user_ids_is_deterministic(users_frame: pd.DataFrame) -> None:
    """The same frame and seed must draw the same sample every time."""
    first = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED)
    second = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED)
    assert list(first) == list(second)


def test_sample_user_ids_changes_with_seed(users_frame: pd.DataFrame) -> None:
    """A different seed must be free to draw a different sample."""
    first = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED)
    second = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED + 1)
    assert list(first) != list(second)


def test_sample_user_ids_returns_every_id_when_population_is_smaller(
    users_frame: pd.DataFrame,
) -> None:
    """Asking for more than exist returns the whole eligible population,
    not a truncated or erroring result.
    """
    selected = sample_user_ids(users_frame, 500, seed=DEFAULT_SAMPLE_SEED)
    assert sorted(selected) == sorted(users_frame["user_id"].unique())


def test_describe_user_sample_reports_the_fields_a_reader_needs(
    users_frame: pd.DataFrame,
) -> None:
    """Seed, eligible population, selected count/fraction, distinct
    users, time range and a digest of what was actually selected --
    the fields a report needs to state what it measured, not just how
    many.
    """
    selected = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED)
    description = describe_user_sample(users_frame, selected, seed=DEFAULT_SAMPLE_SEED)

    assert description["method"] == "seeded uniform random without replacement"
    assert description["seed"] == DEFAULT_SAMPLE_SEED
    assert description["eligible_users"] == 200
    assert description["selected_users"] == 20
    assert description["distinct_users"] == 20
    assert description["selected_fraction"] == pytest.approx(20 / 200)
    assert isinstance(description["selected_ids_sha256"], str)
    assert len(description["selected_ids_sha256"]) == 64
    assert "start" in description["time_range"]
    assert "end" in description["time_range"]


def test_describe_user_sample_digest_is_reproducible(users_frame: pd.DataFrame) -> None:
    """The same sample must always hash to the same digest, so a rerun
    can confirm it drew the same users without publishing the ids.
    """
    selected = sample_user_ids(users_frame, 20, seed=DEFAULT_SAMPLE_SEED)
    first = describe_user_sample(users_frame, selected, seed=DEFAULT_SAMPLE_SEED)
    second = describe_user_sample(users_frame, selected, seed=DEFAULT_SAMPLE_SEED)
    assert first["selected_ids_sha256"] == second["selected_ids_sha256"]


@pytest.mark.parametrize(
    "publish_fn",
    [publish_explanation_report, publish_serving_latency_report],
    ids=["publish_explanation_report", "publish_serving_latency_report"],
)
def test_bounded_report_publisher_requires_sampling(publish_fn) -> None:
    """A bounded, per-user evaluation's publisher must not be callable
    without real sampling metadata -- there is no default to fall back
    to, so a caller that omits it fails immediately with a TypeError
    rather than silently publishing FULL_POPULATION for a sample.
    """
    with pytest.raises(TypeError):
        publish_fn({"total_recommendations_evaluated": 1})


@pytest.mark.parametrize(
    "publish_fn",
    [publish_explanation_report, publish_serving_latency_report],
    ids=["publish_explanation_report", "publish_serving_latency_report"],
)
def test_bounded_report_publisher_sampling_has_no_default(publish_fn) -> None:
    """Belt and braces on the check above: inspect the signature itself,
    so this fails loudly if a future edit reintroduces a default instead
    of only breaking the runtime-call test.
    """
    sampling_param = inspect.signature(publish_fn).parameters["sampling"]
    assert sampling_param.default is inspect.Parameter.empty
