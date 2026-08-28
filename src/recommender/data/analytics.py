from pathlib import Path

import duckdb
import pandas as pd

from recommender.paths import mind_small_path

PROCESSED_DIR = mind_small_path()

CTR_BY_CATEGORY_SQL = """
WITH tokens AS (
    SELECT unnest(string_split(impressions, ' ')) AS token
    FROM read_parquet('{behaviors_path}')
),
exploded AS (
    SELECT
        string_split(token, '-')[1] AS news_id,
        CAST(string_split(token, '-')[2] AS INTEGER) AS clicked
    FROM tokens
)
SELECT
    n.category,
    COUNT(*) AS impressions,
    SUM(e.clicked) AS clicks,
    ROUND(SUM(e.clicked) * 1.0 / COUNT(*), 4) AS ctr,
    RANK() OVER (ORDER BY SUM(e.clicked) * 1.0 / COUNT(*) DESC) AS ctr_rank
FROM exploded e
JOIN read_parquet('{news_path}') n ON e.news_id = n.news_id
GROUP BY n.category
ORDER BY ctr_rank
"""


def click_rate_by_category(split: str, processed_dir: Path = PROCESSED_DIR) -> pd.DataFrame:
    split_dir = processed_dir / split
    sql = CTR_BY_CATEGORY_SQL.format(
        behaviors_path=(split_dir / "behaviors.parquet").as_posix(),
        news_path=(split_dir / "news.parquet").as_posix(),
    )
    return duckdb.sql(sql).df()
