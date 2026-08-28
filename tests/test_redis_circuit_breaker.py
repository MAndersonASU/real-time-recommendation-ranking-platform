from recommender.features.state_store import RedisCircuitBreaker


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_closed_breaker_always_allows_requests():
    breaker = RedisCircuitBreaker(failure_threshold=3, cooldown_seconds=5.0)

    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.allow_request() is True  # below threshold
    assert breaker.is_open is False


def test_breaker_opens_only_on_consecutive_failures_reaching_the_threshold():
    breaker = RedisCircuitBreaker(failure_threshold=3, cooldown_seconds=5.0)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False
    breaker.record_failure()
    assert breaker.is_open is True


def test_a_success_resets_the_consecutive_failure_count():
    breaker = RedisCircuitBreaker(failure_threshold=3, cooldown_seconds=5.0)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    # Two more failures after the reset -- still below the threshold of
    # three consecutive ones, so it must not have opened.
    assert breaker.is_open is False


def test_breaker_closes_again_after_the_cooldown_elapses():
    clock = _FakeClock()
    breaker = RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, clock=clock)

    breaker.record_failure()
    assert breaker.allow_request() is False

    clock.advance(4.9)
    assert breaker.allow_request() is False

    clock.advance(0.2)  # now past the 5-second cooldown
    assert breaker.allow_request() is True


def test_a_recorded_success_after_the_probe_closes_the_breaker():
    clock = _FakeClock()
    breaker = RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, clock=clock)

    breaker.record_failure()
    clock.advance(10.0)
    assert breaker.allow_request() is True  # the probe is let through

    breaker.record_success()
    assert breaker.is_open is False
    clock.advance(-10.0)  # even back "inside" the old cooldown window
    assert breaker.allow_request() is True


def test_a_failed_probe_reopens_the_breaker_for_another_full_cooldown():
    clock = _FakeClock()
    breaker = RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, clock=clock)

    breaker.record_failure()
    clock.advance(10.0)
    assert breaker.allow_request() is True  # probe allowed
    breaker.record_failure()  # probe itself failed

    assert breaker.allow_request() is False
    clock.advance(4.9)
    assert breaker.allow_request() is False
    clock.advance(0.2)
    assert breaker.allow_request() is True
