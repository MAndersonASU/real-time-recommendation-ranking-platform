import pandas as pd

from recommender.features.online_features import (
    DurableUserFeatures,
    RecentUserFeatures,
    compute_durable_features,
    recent_features_from_user_state,
)
from recommender.streaming.consumer import StreamConsumer
from recommender.streaming.schema import EventType, make_event

NEWS = pd.DataFrame(
    {
        "news_id": ["n1", "n2", "n3", "n4"],
        "category": ["sports", "sports", "tech", "tech"],
    }
)


def test_durable_features_use_each_users_longest_available_history():
    behaviors = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "time": pd.to_datetime(
                ["2019-11-10 08:00:00", "2019-11-11 09:00:00", "2019-11-10 08:00:00"]
            ),
            "history": ["n1 n2", "n1 n2 n3", "n3 n4"],
        }
    )

    features = compute_durable_features(behaviors, NEWS)

    assert features["u1"] == DurableUserFeatures(
        user_id="u1", dominant_category="sports", lifetime_click_count=3
    )
    assert features["u2"] == DurableUserFeatures(
        user_id="u2", dominant_category="tech", lifetime_click_count=2
    )


def test_durable_features_have_no_dominant_category_for_empty_history():
    behaviors = pd.DataFrame(
        {"user_id": ["u3"], "time": pd.to_datetime(["2019-11-10 08:00:00"]), "history": [None]}
    )

    features = compute_durable_features(behaviors, NEWS)

    assert features["u3"].dominant_category is None
    assert features["u3"].lifetime_click_count == 0


def test_recent_features_mirror_the_live_streaming_consumer_state():
    consumer = StreamConsumer()
    consumer.process(make_event(EventType.IMPRESSION, "u1", "n1", 1, "t1").to_json())
    consumer.process(make_event(EventType.CLICK, "u1", "n2", 1, "t2").to_json())

    recent = recent_features_from_user_state("u1", consumer.user_states["u1"])

    assert recent == RecentUserFeatures(
        user_id="u1",
        recent_clicked_items=["n2"],
        impressions_seen=1,
        clicks_seen=1,
        last_event_time="t2",
    )
