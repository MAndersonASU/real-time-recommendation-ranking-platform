import threading

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


def test_exactly_one_of_eight_concurrent_callers_is_allowed_past_cooldown():
    """Regression test for a real bug, found by audit: `allow_request()`
    used to be a stateless `now - opened_at >= cooldown` comparison,
    recomputed fresh on every call with no memory of whether a probe was
    already dispatched -- once the cooldown elapsed, every concurrent
    caller got the same `True` answer at once, the exact thundering
    herd this breaker exists to prevent. Fails on the pre-fix code
    (8 of 8 threads allowed) and passes once the OPEN -> HALF_OPEN
    transition and the probe claim happen atomically under a lock, so
    only the one thread that actually flips the state gets `True`.

    A `Barrier` (not just starting all threads) forces every thread to
    call `allow_request()` at genuinely the same instant, rather than
    relying on OS scheduling to happen to interleave them -- without it,
    this test could pass by accident on a machine that serializes the
    threads widely enough to never race.
    """
    breaker = RedisCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
    breaker.record_failure()  # opens it; cooldown=0.0, so already eligible

    allowed = []
    allowed_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        if breaker.allow_request():
            with allowed_lock:
                allowed.append(threading.current_thread().name)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(allowed) == 1, f"expected exactly 1 allowed probe, got {len(allowed)}: {allowed}"
    assert breaker.is_open is True  # still HALF_OPEN, not closed -- no record_success yet
