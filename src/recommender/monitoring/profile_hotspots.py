import json
import time
from pathlib import Path

import psutil

from recommender.evaluation.contract import load_split
from recommender.retrieval.train import MODEL_PATH as RETRIEVAL_MODEL_PATH
from recommender.serving.contract import RecommendationRequest
from recommender.serving.pipeline import build_serving_context, recommend

RANKING_MODEL_PATH = Path("data/processed/mind_small/ranking_model.joblib")
FAISS_EXACT_INDEX_PATH = Path("data/processed/mind_small/faiss_exact.index")
NUM_REQUESTS = 30


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


def profile_artifact_disk_footprint() -> dict:
    """Real on-disk size of every artifact `ServingContext` loads --
    what actually has to move off disk (or over the network, in a
    deployed service) before a single request can be served.
    """
    return {
        "two_tower_model_mb": round(RETRIEVAL_MODEL_PATH.stat().st_size / (1024 * 1024), 2),
        "ranking_model_mb": round(RANKING_MODEL_PATH.stat().st_size / (1024 * 1024), 2),
        "faiss_exact_index_mb": round(FAISS_EXACT_INDEX_PATH.stat().st_size / (1024 * 1024), 2),
    }


def profile_context_build_memory() -> dict:
    """Real process RSS before and after `build_serving_context()` --
    the actual memory cost of standing up a server process, measured
    directly rather than estimated from artifact sizes alone (in-memory
    representations, e.g. a rebuilt Faiss index, don't have to match
    their on-disk size).
    """
    before_mb = _rss_mb()
    start = time.perf_counter()
    context = build_serving_context()
    build_seconds = time.perf_counter() - start
    after_mb = _rss_mb()
    return {
        "rss_before_mb": round(before_mb, 1),
        "rss_after_mb": round(after_mb, 1),
        "rss_delta_mb": round(after_mb - before_mb, 1),
        "build_seconds": round(build_seconds, 2),
    }, context


def profile_stage_cpu_vs_wall(context, num_requests: int = NUM_REQUESTS) -> dict:
    """CPU time (`time.process_time`) alongside wall time
    (`time.perf_counter`) for each of the six request stages measured in
    `docs/serving-latency.md`, averaged over real requests. The two
    diverging for a stage would mean it spends real time waiting on
    something (network, disk) rather than computing -- this is the one
    profiling angle `docs/serving-latency.md`'s own wall-clock-only
    numbers couldn't tell apart.
    """
    users = load_split("validation")["user_id"].drop_duplicates().head(num_requests).tolist()

    wall_totals: dict[str, float] = {}
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    for user_id in users:
        stage_timings: dict[str, float] = {}
        recommend(RecommendationRequest(user_id=user_id, num_candidates=10), context, stage_timings=stage_timings)
        for stage, ms in stage_timings.items():
            wall_totals[stage] = wall_totals.get(stage, 0.0) + ms
    total_cpu_seconds = time.process_time() - cpu_start
    total_wall_seconds = time.perf_counter() - wall_start

    return {
        "requests": len(users),
        "total_cpu_seconds": round(total_cpu_seconds, 3),
        "total_wall_seconds": round(total_wall_seconds, 3),
        "cpu_to_wall_ratio": round(total_cpu_seconds / total_wall_seconds, 3) if total_wall_seconds else None,
        "wall_ms_by_stage_summed": {k: round(v, 1) for k, v in wall_totals.items()},
    }


def profile_hotspots() -> dict:
    disk = profile_artifact_disk_footprint()
    memory, context = profile_context_build_memory()
    cpu = profile_stage_cpu_vs_wall(context)
    return {"disk_footprint": disk, "context_build_memory": memory, "stage_cpu_vs_wall": cpu}


def main() -> None:
    report = profile_hotspots()
    report_path = Path("data/processed/mind_small/profile_hotspots_report.json")
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
