from recommender.features.state_store import build_client


def test_build_client_sets_a_real_connect_and_read_timeout_by_default():
    """Regression test for a real bug, found by audit: build_client had
    no socket timeout at all, so a Redis that hangs instead of refusing
    the connection outright would block a request forever rather than
    raising the RedisError safe_recommend relies on to fall back. Fails
    on the pre-fix code (both timeouts are None) and passes once a real,
    finite default is set.
    """
    client = build_client()

    connection_kwargs = client.connection_pool.connection_kwargs
    assert connection_kwargs["socket_connect_timeout"] is not None
    assert connection_kwargs["socket_connect_timeout"] > 0
    assert connection_kwargs["socket_timeout"] is not None
    assert connection_kwargs["socket_timeout"] > 0


def test_build_client_lets_a_caller_override_the_timeouts():
    client = build_client(socket_connect_timeout=5.0, socket_timeout=7.0)

    connection_kwargs = client.connection_pool.connection_kwargs
    assert connection_kwargs["socket_connect_timeout"] == 5.0
    assert connection_kwargs["socket_timeout"] == 7.0
