"""The fit-half bundle must stay separate from the deployed one, and a
tuning run must say which of the two it used.

These are the two ways the leakage fix could be quietly undone: by the
fit-half training run overwriting the deployed artifacts (making the
served model worse in exchange for tuning honesty nobody asked for), or
by a tuning run silently falling back to the leaked feature table and
reporting its numbers as if they were held out.
"""

import pandas as pd
import pytest

from recommender.ranking.build_dataset import TRAIN_PATH
from recommender.ranking.build_dataset_fit_only import (
    FIT_ONLY_TRAIN_PATH,
    FitOnlyArtifactsMissing,
)
from recommender.retrieval.content_artifact import CONTENT_ARTIFACT_PATH
from recommender.retrieval.train import MODEL_PATH
from recommender.retrieval.train_fit_only import (
    FIT_ONLY_BUNDLE_PATH,
    FIT_ONLY_CONTENT_PATH,
    FIT_ONLY_MODEL_PATH,
)


class _AbsentPath:
    """A stand-in for an artifact that has not been built on this machine.

    `Path.exists` cannot be patched on an instance, and patching it on the
    class would change the answer for every unrelated path a test touches.
    """

    name = "two_tower_model_fit_only.pt"

    def exists(self) -> bool:
        return False


class _PresentPath(_AbsentPath):
    def exists(self) -> bool:
        return True


def test_the_fit_half_bundle_writes_to_its_own_paths():
    """Not a stylistic preference. The fit-half model is trained on 80%
    of the data on purpose, which makes it a worse model to serve;
    letting it land on the deployed paths would trade real serving
    quality for an evaluation property.
    """
    assert FIT_ONLY_MODEL_PATH != MODEL_PATH
    assert FIT_ONLY_CONTENT_PATH != CONTENT_ARTIFACT_PATH
    assert FIT_ONLY_TRAIN_PATH != TRAIN_PATH
    for path in (FIT_ONLY_MODEL_PATH, FIT_ONLY_CONTENT_PATH, FIT_ONLY_BUNDLE_PATH):
        assert "fit_only" in path.name


def test_the_fit_half_fold_matches_the_tuning_fold_exactly():
    """The fit-half model must be blind to precisely the impressions the
    tuning fold is made of. A different seed here would leave the model
    trained on part of the fold it is supposed to be held out from --
    the original defect, moved rather than fixed.
    """
    from recommender.evaluation.tuning_fold import TUNE_FOLD_SEED, split_train_for_tuning
    from recommender.retrieval import train_fit_only

    assert train_fit_only.TUNE_FOLD_SEED == TUNE_FOLD_SEED

    behaviors = pd.DataFrame(
        {
            "impression_id": [f"i{i}" for i in range(500)],
            "user_id": [f"U{i % 40}" for i in range(500)],
        }
    )
    fit_a, tune_a = split_train_for_tuning(behaviors)
    fit_b, tune_b = split_train_for_tuning(behaviors)

    assert list(fit_a["impression_id"]) == list(fit_b["impression_id"])
    assert not set(fit_a["impression_id"]) & set(tune_a["impression_id"])
    assert len(tune_b) > 0


def test_building_fit_only_features_refuses_to_substitute_the_deployed_model(monkeypatch):
    """Falling back to the deployed retrieval model would produce a table
    that looks fit-half-only and is not. Refusing forces the fit-half
    model to actually be built.
    """
    import recommender.ranking.build_dataset_fit_only as module

    monkeypatch.setattr(module, "FIT_ONLY_MODEL_PATH", _AbsentPath())

    with pytest.raises(FitOnlyArtifactsMissing, match="must not be substituted"):
        module.build_and_save()


def test_a_tuning_run_records_which_feature_table_it_used(monkeypatch):
    """A leaked run and a clean one must not look the same in the
    published report. Falling back is allowed -- the fit-half bundle is
    expensive and may not exist -- but it is recorded as leaked, not
    passed off as held out.
    """
    from recommender.evaluation import verify_tuning_decisions as module

    frame = pd.DataFrame({"impression_id": ["i1"], "clicked": [1]})
    monkeypatch.setattr(module.pd, "read_parquet", lambda *_a, **_k: frame)

    import recommender.ranking.build_dataset_fit_only as fit_only_module

    monkeypatch.setattr(fit_only_module, "FIT_ONLY_TRAIN_PATH", _PresentPath())
    _rows, clean = module._load_tuning_rows()
    assert clean["tune_fold_leakage"] is False
    assert clean["feature_table"] == "fit_half_only"

    monkeypatch.setattr(fit_only_module, "FIT_ONLY_TRAIN_PATH", _AbsentPath())
    _rows, leaked = module._load_tuning_rows()
    assert leaked["tune_fold_leakage"] is True
    assert "train_fit_only" in leaked["note"]
