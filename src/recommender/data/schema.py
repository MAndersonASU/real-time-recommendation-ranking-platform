NEWS_COLUMNS = [
    "news_id",
    "category",
    "subcategory",
    "title",
    "abstract",
    "url",
    "title_entities",
    "abstract_entities",
]

BEHAVIORS_COLUMNS = [
    "impression_id",
    "user_id",
    "time",
    "history",
    "impressions",
]

NEWS_REQUIRED_NONNULL = ["news_id", "title"]
BEHAVIORS_REQUIRED_NONNULL = ["impression_id", "user_id", "time", "impressions"]


class SchemaError(ValueError):
    pass


def validate_news(df):
    if list(df.columns) != NEWS_COLUMNS:
        raise SchemaError(f"news columns {list(df.columns)} != {NEWS_COLUMNS}")
    for col in NEWS_REQUIRED_NONNULL:
        if df[col].isna().any():
            raise SchemaError(f"news.{col} contains unexpected nulls")
    if df["news_id"].duplicated().any():
        raise SchemaError("news_id is not unique")


def validate_behaviors(df):
    if list(df.columns) != BEHAVIORS_COLUMNS:
        raise SchemaError(f"behaviors columns {list(df.columns)} != {BEHAVIORS_COLUMNS}")
    for col in BEHAVIORS_REQUIRED_NONNULL:
        if df[col].isna().any():
            raise SchemaError(f"behaviors.{col} contains unexpected nulls")
