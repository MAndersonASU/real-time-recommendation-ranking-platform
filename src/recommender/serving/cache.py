import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from recommender.features.online_features import DurableUserFeatures, compute_durable_features

# Matches the "refreshed daily" design intent for a system with live
# data. This project's data are a frozen 2019 snapshot, so this
# threshold is always exceeded by design -- see the note on `is_stale`.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60.0


@dataclass
class DurableFeatureCache:
    """Durable features (`docs/operations/online-features.md`) are computed offline
    and refreshed occasionally, not per request.

    Two different times matter here, and conflating them is what made an
    earlier version misleading:

    - `built_at` is when this process constructed the snapshot. It moves
      every restart.
    - `data_as_of` is the newest event in the data the snapshot was
      built from. It does not move on restart, because restarting does
      not make the underlying data any newer.

    The earlier version had only one timestamp, set to `now()` at build
    time, so restarting the service relabelled a frozen 2019 snapshot as
    freshly computed. Staleness is therefore measured against
    `data_as_of`.

    This cache reports staleness; it never refreshes itself inside a
    request. Recomputing means re-reading an offline split and
    rebuilding the whole dict -- batch-shaped work a live request path
    should not trigger.
    """

    features_by_user: dict[str, DurableUserFeatures]
    built_at: datetime
    data_as_of: datetime | None
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS

    def get(self, user_id: str) -> DurableUserFeatures | None:
        return self.features_by_user.get(user_id)

    def data_age_seconds(self, now: datetime | None = None) -> float | None:
        """Age of the underlying *data*, not of this process's copy of
        it. None when the source carried no usable timestamp.
        """
        if self.data_as_of is None:
            return None
        now = now if now is not None else datetime.now(UTC)
        return (now - self.data_as_of).total_seconds()

    def is_stale(self, now: datetime | None = None) -> bool:
        """True when the underlying data are older than the threshold.

        For this project that is always true: the MIND snapshot is from
        November 2019 and is never refreshed. That is the honest answer
        rather than a bug -- the alternative, measuring against
        `built_at`, would report a years-old snapshot as fresh purely
        because the process restarted.
        """
        age = self.data_age_seconds(now)
        if age is None:
            return True
        return age > self.max_age_seconds

    def snapshot_id(self) -> str:
        """A stable identifier for *which* snapshot this is.

        Derived from the feature values it contains, not from when it was
        loaded, so two processes that built the same snapshot report the
        same id and a genuinely different snapshot reports a different
        one.

        An earlier version claimed exactly that and delivered neither.
        It summed `hash(user_id)` over the user set, which broke both
        halves of the promise:

        - Python randomises `hash()` for `str` per process (PEP 456), so
          the same snapshot produced a different id on every restart.
          Two processes here produced `f4e32d2dcdbf` and `10351e8a25d3`
          from identical data.
        - It hashed only the *user set*, never the feature values, so
          recomputing features for the same users at the same
          `data_as_of` left the id unchanged -- the one case where the
          id most needs to move, because serving behaviour changes while
          the reported version does not.

        Every published field of every record now goes into the digest,
        in sorted user order, through SHA-256. Cost is linear in the
        number of users and is paid once per snapshot build, not per
        request.

        `history_item_ids` (SERVING-DURABLE-HISTORY-69) is included as a
        length-prefixed sequence, not simply joined: without a length
        prefix per element, `("ab", "c")` and `("a", "bc")` would encode
        to the same bytes, the same ambiguity this project's content-
        artifact checksum already guards against
        (ARTIFACT-VALIDATION-05).
        """
        digest = hashlib.sha256()
        # Version tag bumped to v2: a snapshot computed before this field
        # existed and one computed after it, from data that happens to
        # produce the same first three fields, must not silently collide.
        digest.update(b"durable-feature-snapshot-v2\n")
        digest.update(f"data_as_of={self.data_as_of}\n".encode())
        digest.update(f"users={len(self.features_by_user)}\n".encode())

        # Sorted, so the id does not depend on dict insertion order --
        # which follows the order rows arrived from the split file and is
        # not part of the snapshot's identity.
        for user_id in sorted(self.features_by_user):
            features = self.features_by_user[user_id]
            # Field-tagged and newline-delimited rather than concatenated:
            # without separators, ("ab", "c") and ("a", "bc") would
            # produce the same bytes.
            digest.update(
                (
                    f"user_id={features.user_id}\n"
                    f"dominant_category={features.dominant_category}\n"
                    f"lifetime_click_count={features.lifetime_click_count}\n"
                    f"history_item_count={len(features.history_item_ids)}\n"
                ).encode()
            )
            for item_id in features.history_item_ids:
                digest.update(f"history_item_len={len(item_id)}\n{item_id}\n".encode())
        return digest.hexdigest()[:12]

    def describe(self, now: datetime | None = None) -> dict:
        """Operator-visible metadata, surfaced through `/ready`.

        Deliberately labels the snapshot as historical rather than
        implying a refresh pipeline exists.
        """
        age = self.data_age_seconds(now)
        return {
            "snapshot_id": self.snapshot_id(),
            "built_at": self.built_at.isoformat(),
            "data_as_of": self.data_as_of.isoformat() if self.data_as_of else None,
            "data_age_seconds": age,
            "users": len(self.features_by_user),
            "is_stale": self.is_stale(now),
            "refresh_policy": (
                "frozen historical snapshot; not refreshed. Restarting the service "
                "reloads the same data and does not make it newer."
            ),
        }


def _latest_event_time(behaviors: pd.DataFrame) -> datetime | None:
    if "time" not in behaviors.columns or behaviors.empty:
        return None
    latest = pd.to_datetime(behaviors["time"], errors="coerce").max()
    if pd.isna(latest):
        return None
    stamp = latest.to_pydatetime()
    # MIND does not document its timestamps' timezone at all
    # (`docs/engineering-review-register.md`'s FEATURE-TIMEZONE-20) --
    # UTC is a pragmatic, disclosed assumption this project makes for
    # comparison purposes, not a documented dataset fact. Attaching it
    # here means comparisons against a real clock are at least between
    # two aware values, not a claim that the assumption is verified.
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def build_durable_feature_cache(
    behaviors: pd.DataFrame, news: pd.DataFrame, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> DurableFeatureCache:
    return DurableFeatureCache(
        features_by_user=compute_durable_features(behaviors, news),
        built_at=datetime.now(UTC),
        data_as_of=_latest_event_time(behaviors),
        max_age_seconds=max_age_seconds,
    )


def refresh(cache: DurableFeatureCache, behaviors: pd.DataFrame, news: pd.DataFrame) -> DurableFeatureCache:
    """Recomputes the cache from the given data and returns a new one
    rather than mutating in place, so a caller holding the old reference
    still sees a consistent snapshot.

    No scheduler calls this. Automated atomic refresh is future work,
    not a missing production feature: this project serves a frozen
    historical dataset, and pretending otherwise would be the misleading
    claim.
    """
    return build_durable_feature_cache(behaviors, news, max_age_seconds=cache.max_age_seconds)
