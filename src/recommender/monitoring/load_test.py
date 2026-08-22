import itertools
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from recommender.serving.contract import RecommendationRequest
from recommender.serving.fallback import safe_recommend
from recommender.serving.pipeline import ServingContext

DEFAULT_CONCURRENCY_LEVELS = (1, 4, 8, 16, 32)
DEFAULT_REQUESTS_PER_LEVEL = 100


def _timed_request(context: ServingContext, user_id: str) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        safe_recommend(RecommendationRequest(user_id=user_id, num_candidates=10), context)
        return time.perf_counter() - start, True
    except Exception:  # noqa: BLE001 -- a load test counts every failure as an error, whatever its cause
        return time.perf_counter() - start, False


def _percentile(sorted_values: list, pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(int(len(sorted_values) * pct / 100), len(sorted_values) - 1)
    return sorted_values[index]


def run_load_test(context: ServingContext, user_ids: list, concurrency: int, num_requests: int) -> dict:
    """Generates real concurrent traffic against the real `safe_recommend`
    path with a thread pool -- Python threads share one process's real
    CPU budget, so this genuinely exercises the CPU contention profiling
    found underneath a single request, unlike a process pool, which
    would hand each request its own core allocation and hide it.
    """
    cycle = itertools.islice(itertools.cycle(user_ids), num_requests)
    latencies_s: list[float] = []
    errors = 0

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_timed_request, context, user_id) for user_id in cycle]
        for future in as_completed(futures):
            latency, ok = future.result()
            latencies_s.append(latency)
            if not ok:
                errors += 1
    total_wall_seconds = time.perf_counter() - start

    latencies_ms = sorted(seconds * 1000 for seconds in latencies_s)
    n = len(latencies_ms)
    return {
        "concurrency": concurrency,
        "requests": n,
        "errors": errors,
        "error_rate": round(errors / n, 4) if n else 0.0,
        "total_wall_seconds": round(total_wall_seconds, 3),
        "throughput_rps": round(n / total_wall_seconds, 2) if total_wall_seconds else 0.0,
        "p50_ms": round(_percentile(latencies_ms, 50), 2),
        "p95_ms": round(_percentile(latencies_ms, 95), 2),
        "p99_ms": round(_percentile(latencies_ms, 99), 2),
    }


def sweep_concurrency(
    context: ServingContext,
    user_ids: list,
    concurrency_levels: tuple = DEFAULT_CONCURRENCY_LEVELS,
    requests_per_level: int = DEFAULT_REQUESTS_PER_LEVEL,
) -> list:
    """Runs `run_load_test` at each concurrency level in turn -- the
    actual shape of a saturation measurement: throughput and latency
    only mean something relative to how they change as concurrency
    rises, not as one single number.
    """
    return [
        run_load_test(context, user_ids, concurrency=level, num_requests=requests_per_level)
        for level in concurrency_levels
    ]
