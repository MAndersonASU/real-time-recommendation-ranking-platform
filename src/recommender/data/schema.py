import re

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

# One (news_id)-(label) pair, label strictly 0 or 1 -- exactly the token
# shape `explode_impressions` (recommender.data.mind) parses with
# `rsplit("-", n=1)`. A field with no real structural check here means a
# malformed token reaches that parser silently: an empty impressions
# field explodes to a single garbage row, a label outside {0, 1} still
# passes `astype("int8")` as a nonsense click value instead of raising,
# and a token with more than one "-" (an edge case rsplit already
# handles correctly by splitting on the *last* one, but never checked to
# be correct) went unverified until now.
# nosec B105 -- this is the regex for a MIND impression token
# ("<news_id>-<0|1>"), not a credential. Bandit's hardcoded-password
# heuristic matches on the variable name containing "TOKEN".
_IMPRESSION_TOKEN_PATTERN = r"[^\s-]+-[01]"  # nosec B105
IMPRESSIONS_FIELD_PATTERN = re.compile(rf"^{_IMPRESSION_TOKEN_PATTERN}( {_IMPRESSION_TOKEN_PATTERN})*$")
HISTORY_FIELD_PATTERN = re.compile(r"^[^\s-]+( [^\s-]+)*$")


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

    malformed = ~df["impressions"].str.fullmatch(IMPRESSIONS_FIELD_PATTERN)
    if malformed.any():
        bad_rows = df.index[malformed][:5].tolist()
        raise SchemaError(
            f"behaviors.impressions has a malformed token (expected 'news_id-0' or "
            f"'news_id-1', space-separated) at row(s) {bad_rows}"
        )

    # history is legitimately absent for a user with no prior clicks
    # (not in BEHAVIORS_REQUIRED_NONNULL), so only its non-null rows are
    # checked -- dropna() first, rather than any boolean-mask algebra
    # across null and non-null rows together, since a null entry has no
    # well-defined "matches the pattern" answer at all.
    non_null_history = df["history"].dropna()
    malformed_history = ~non_null_history.str.fullmatch(HISTORY_FIELD_PATTERN)
    if malformed_history.any():
        bad_rows = non_null_history.index[malformed_history][:5].tolist()
        raise SchemaError(f"behaviors.history has a malformed entry at row(s) {bad_rows}")
