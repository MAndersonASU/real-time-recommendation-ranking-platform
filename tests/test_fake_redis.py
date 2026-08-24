from recommender.features.fake_redis import InMemoryRedis


def test_get_returns_none_for_a_missing_key():
    client = InMemoryRedis()

    assert client.get("missing") is None


def test_set_then_get_round_trips():
    client = InMemoryRedis()

    client.set("k", "v")

    assert client.get("k") == "v"


def test_ping_always_succeeds():
    assert InMemoryRedis().ping() is True


def test_two_instances_are_fully_isolated_from_each_other():
    a = InMemoryRedis()
    b = InMemoryRedis()

    a.set("k", "from_a")

    assert b.get("k") is None
