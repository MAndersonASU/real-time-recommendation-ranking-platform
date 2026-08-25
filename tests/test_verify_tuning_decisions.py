import pandas as pd

from recommender.evaluation.verify_tuning_decisions import (
    _compare_diversity_cap_values,
    _compare_freshness_threshold_values,
    _coverage_at_threshold,
)

NEWS = pd.DataFrame(
    {
        "news_id": [f"n{i}" for i in range(1, 9)],
        "category": ["sports", "sports", "sports", "tech", "tech", "tech", "news", "news"],
        "subcategory": ["football", "football", "tennis", "gadgets", "ai", "ai", "world", "local"],
        "title": [
            "team wins big game", "striker scores twice", "tennis final result",
            "new phone released", "ai model breakthrough", "ai research lab opens",
            "world summit begins", "local council meets",
        ],
        "abstract": [""] * 8,
        "url": [""] * 8,
        "title_entities": ["[]"] * 8,
        "abstract_entities": ["[]"] * 8,
    }
)
CATEGORY_BY_ID = NEWS.set_index("news_id")["category"]


def test_coverage_at_threshold_reports_the_real_fresh_row_and_zero_fresh_rates():
    tune_rows = pd.DataFrame({"impression_id": [1, 1, 2], "news_id": ["n1", "n2", "n3"]})
    impression_time = pd.Series(
        {1: pd.Timestamp("2019-11-12"), 2: pd.Timestamp("2019-11-12")}
    )
    first_seen = pd.Series({"n1": pd.Timestamp("2019-11-10"), "n2": pd.Timestamp("2019-11-01")})
    # n1: 2 days old (fresh at 3-day threshold). n2: 11 days old (stale).
    # n3: no real first-seen time at all -- unknown, not zero.

    result = _coverage_at_threshold(tune_rows, impression_time, first_seen, threshold_days=3.0)

    assert result["impressions_checked"] == 2
    # 1 of 3 rows fresh (n1) -- n2 stale, n3 unknown (never counted as fresh).
    assert result["fresh_row_rate"] == 1 / 3
    # Impression 1 has a fresh row (n1); impression 2 (only n3, unknown
    # age) has none -- exactly one of two impressions is zero-fresh.
    assert result["zero_fresh_impression_rate"] == 0.5


def test_compare_freshness_threshold_values_selects_the_smallest_threshold_meeting_the_rule():
    # A real, constructed scenario: coverage improves as the threshold
    # widens, so the rule (smallest threshold with <5% zero-fresh rate)
    # should pick a real, specific, non-trivial threshold, not always
    # the smallest or largest candidate by construction.
    rows = []
    for impression_id in range(200):
        # Every impression has one item first-seen exactly 0.4 days
        # before it -- fresh at every threshold >= 0.5 (and the default
        # 0.5 already used in production), stale at 0.25.
        rows.append({"impression_id": impression_id, "news_id": "n1"})
    tune_rows = pd.DataFrame(rows)
    impression_time = pd.Series({i: pd.Timestamp("2019-11-12T00:00:00") for i in range(200)})
    first_seen = pd.Series({"n1": pd.Timestamp("2019-11-11T14:24:00")})  # 0.4 days before

    result = _compare_freshness_threshold_values(tune_rows, impression_time, first_seen)

    assert result["by_threshold_days"]["0.25"]["zero_fresh_impression_rate"] == 1.0  # nothing clears 0.25
    assert result["by_threshold_days"]["0.5"]["zero_fresh_impression_rate"] == 0.0  # everything clears 0.5
    assert result["threshold_selected_by_rule"] == 0.5
    assert result["rule_supports_current_configuration"] is True


def test_compare_diversity_cap_values_reports_real_relevance_and_diversity_per_cap():
    # 4 candidates per impression, 2 sports + 2 tech, descending score --
    # a cap of 1 forces the algorithm to reach past same-category items
    # for a second category; no cap keeps the naive score order.
    rows = []
    for impression_id in range(5):
        rows.append({"impression_id": impression_id, "news_id": "n1", "ranked_score": 0.9})
        rows.append({"impression_id": impression_id, "news_id": "n2", "ranked_score": 0.8})
        rows.append({"impression_id": impression_id, "news_id": "n4", "ranked_score": 0.7})
        rows.append({"impression_id": impression_id, "news_id": "n5", "ranked_score": 0.6})
    scored_rows = pd.DataFrame(rows)

    result = _compare_diversity_cap_values(
        scored_rows, CATEGORY_BY_ID, sample_impressions=5, news=NEWS
    )

    assert result["sample_impressions"] == 5
    assert set(result["by_cap_value"].keys()) == {"1", "2", "3", "5", "no_cap"}
    # A cap of 1 must produce at least as much category diversity as no
    # cap at all, for the same real candidates.
    cap_1_diversity = result["by_cap_value"]["1"]["mean_distinct_categories"]
    no_cap_diversity = result["by_cap_value"]["no_cap"]["mean_distinct_categories"]
    assert cap_1_diversity >= no_cap_diversity
    assert result["selection_rule"]
    by_budget = result["cap_selected_by_relevance_budget"]
    assert set(by_budget.keys()) == {"0.85", "0.90", "0.95", "0.99"}
    assert all(cap in {1, 2, 3, 5, None} for cap in by_budget.values())


def test_diversity_budget_rule_is_not_trivially_satisfied_by_the_smallest_cap():
    """The rule this replaced could not work: slate diversity rises
    monotonically as the cap falls, so a bar stated relative to the
    uncapped (least diverse) case was cleared by every capped value and
    always selected the smallest cap tried, whatever it cost in
    relevance. A relevance budget is not monotone that way -- an
    aggressive cap spends relevance to buy diversity, so a tight budget
    must be able to rule it out.

    Needs more candidates than the 10-item slate, otherwise every cap
    returns the same full slate and no cap can cost anything.
    """
    # 12 strong sports items and 8 weak items spread over other
    # categories: capping sports forces the algorithm to reach past the
    # strong items into much weaker ones, which is genuinely expensive.
    # Every title uses distinct vocabulary. build_diverse_slate also
    # rejects near-duplicates by TF-IDF cosine, so formulaic titles
    # ("topic 1", "topic 2", ...) get filtered as duplicates and the
    # unconstrained fill pass then reloads the slate with high-scoring
    # sports items -- which silently destroys the tension this fixture
    # exists to create.
    sports_words = [
        "striker", "goalkeeper", "marathon", "tennis", "cycling", "boxing",
        "swimming", "rowing", "hockey", "sprint", "archery", "surfing",
    ]
    other_words = [
        "election", "vaccine", "harvest", "telescope", "currency",
        "opera", "wildfire", "railway",
    ]
    news = pd.DataFrame(
        {
            "news_id": [f"s{i}" for i in range(12)] + [f"o{i}" for i in range(8)],
            "category": ["sports"] * 12 + [f"cat{i}" for i in range(8)],
            "subcategory": ["general"] * 20,
            "title": sports_words + other_words,
            "abstract": [""] * 20,
        }
    )
    category_by_id = news.set_index("news_id")["category"]
    rows = []
    for impression_id in range(5):
        for i in range(12):
            rows.append({"impression_id": impression_id, "news_id": f"s{i}", "ranked_score": 0.9})
        for i in range(8):
            rows.append({"impression_id": impression_id, "news_id": f"o{i}", "ranked_score": 0.01})
    scored_rows = pd.DataFrame(rows)

    result = _compare_diversity_cap_values(
        scored_rows, category_by_id, sample_impressions=5, news=news
    )

    by_cap = result["by_cap_value"]
    # Reaching for other categories here is genuinely expensive.
    assert by_cap["1"]["mean_slate_relevance"] < by_cap["no_cap"]["mean_slate_relevance"]
    assert by_cap["1"]["mean_distinct_categories"] > by_cap["no_cap"]["mean_distinct_categories"]
    # A strict budget must therefore reject the most aggressive cap,
    # which the old monotonic rule could never do.
    assert result["cap_selected_by_relevance_budget"]["0.99"] != 1
