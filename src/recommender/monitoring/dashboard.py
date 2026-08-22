from recommender.monitoring import metrics as m


def _counter_value(counter, **labels) -> float:
    target = counter.labels(**labels) if labels else counter
    return target._value.get()


def build_dashboard_data() -> dict:
    """Pulls the handful of numbers that actually reveal whether this
    service is healthy and whether recommendation behavior is drifting
    -- directly from the same live, in-process metric objects
    `/metrics` exposes, not a second, separately-computed copy. Real
    percentiles (p50/p95/p99) need a query engine over many scrape
    intervals (what a real Prometheus server + PromQL's
    `histogram_quantile()` does) -- this compact view reports mean
    latency instead, an honest, simpler substitute this in-process page
    can actually compute on its own, not a fabricated percentile.
    """
    success = _counter_value(m.REQUEST_COUNT, outcome="success")
    error = _counter_value(m.REQUEST_COUNT, outcome="error")
    total = success + error

    # Every successful response observes exactly one latency value
    # (`record_response` always calls `.observe()`) and errors never do
    # (`record_error` doesn't touch this histogram at all), so `success`
    # itself is the real observation count -- Histogram has no direct
    # `_count` attribute; only `_sum` and per-bucket values.
    latency_sum = m.REQUEST_LATENCY_SECONDS._sum.get()

    durable_hit = _counter_value(m.DURABLE_CACHE_COUNT, result="hit")
    durable_miss = _counter_value(m.DURABLE_CACHE_COUNT, result="miss")
    recent_hit = _counter_value(m.RECENT_CACHE_COUNT, result="hit")
    recent_miss = _counter_value(m.RECENT_CACHE_COUNT, result="miss")

    return {
        "total_requests": total,
        "error_rate": (error / total) if total else None,
        "mean_latency_ms": (latency_sum / success * 1000) if success else None,
        "fallback_rate": (_counter_value(m.FALLBACK_COUNT) / total) if total else None,
        "empty_response_rate": (_counter_value(m.EMPTY_RESPONSE_COUNT) / total) if total else None,
        "durable_cache_hit_rate": (
            durable_hit / (durable_hit + durable_miss) if (durable_hit + durable_miss) else None
        ),
        "recent_cache_hit_rate": (
            recent_hit / (recent_hit + recent_miss) if (recent_hit + recent_miss) else None
        ),
        # Prometheus Gauges have no "unset" state distinct from a real
        # 0.0 -- these four are only meaningful once at least one real
        # request has been recorded (guarded by `total_requests` above,
        # in the render function, not by treating 0.0 itself as absent
        # here, which would silently misreport a genuine zero).
        "score_mean": m.SCORE_MEAN._value.get(),
        "mean_diversity": m.MEAN_DIVERSITY._value.get(),
        "catalog_coverage": m.CATALOG_COVERAGE._value.get(),
        "top_n_concentration": m.TOP_N_CONCENTRATION._value.get(),
    }


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "&mdash;"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"


def _fmt_pct(value) -> str:
    return "&mdash;" if value is None else f"{value * 100:.1f}%"


def render_dashboard_html() -> str:
    d = build_dashboard_data()
    quality_available = d["total_requests"] > 0
    rows = [
        ("Total requests", _fmt(d["total_requests"])),
        ("Error rate", _fmt_pct(d["error_rate"])),
        ("Mean latency", _fmt(d["mean_latency_ms"], " ms")),
        ("Fallback rate", _fmt_pct(d["fallback_rate"])),
        ("Empty response rate", _fmt_pct(d["empty_response_rate"])),
        ("Durable cache hit rate", _fmt_pct(d["durable_cache_hit_rate"])),
        ("Recent cache hit rate", _fmt_pct(d["recent_cache_hit_rate"])),
        # These four read Prometheus Gauges, which have no "unset" state
        # distinct from a real 0.0 -- gated on a real request having
        # happened at all, rather than trusting a bare zero to mean
        # "no data" (docs/dashboard.md).
        ("Mean score", _fmt(d["score_mean"]) if quality_available else "&mdash;"),
        ("Mean diversity", _fmt(d["mean_diversity"]) if quality_available else "&mdash;"),
        ("Catalog coverage", _fmt_pct(d["catalog_coverage"]) if quality_available else "&mdash;"),
        ("Top-10 concentration", _fmt_pct(d["top_n_concentration"]) if quality_available else "&mdash;"),
    ]
    row_html = "".join(
        f'<tr><td class="label">{label}</td><td class="value">{value}</td></tr>' for label, value in rows
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Recommendation Service Dashboard</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #F3F5F6; color: #1B2430; margin: 0; padding: 2rem; }}
h1 {{ font-family: Georgia, serif; font-weight: 400; font-size: 1.4rem; }}
table {{ border-collapse: collapse; width: 100%; max-width: 480px; background: #fff; border-radius: 8px; overflow: hidden; }}
td {{ padding: 0.6rem 1rem; border-bottom: 1px solid #E8ECEE; }}
.label {{ color: #4C5966; }}
.value {{ text-align: right; font-family: monospace; font-weight: 700; color: #276E6B; }}
</style></head>
<body><h1>Recommendation Service &mdash; Live Status</h1>
<table>{row_html}</table>
</body></html>"""
