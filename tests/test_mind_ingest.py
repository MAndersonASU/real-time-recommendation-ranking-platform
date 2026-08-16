import pandas as pd
import pytest

from recommender.data.mind import explode_impressions, load_behaviors, load_news
from recommender.data.schema import SchemaError, validate_behaviors, validate_news

NEWS_ROW = "N1\tsports\tfootball\tSome Title\tSome abstract\thttp://x\t[]\t[]\n"
NEWS_ROW_NO_ABSTRACT = "N2\tsports\tfootball\tOther Title\t\thttp://y\t[]\t[]\n"
BEHAVIORS_ROW = "1\tU1\t11/11/2019 9:05:58 AM\tN1 N2\tN1-1 N2-0\n"
BEHAVIORS_ROW_NO_HISTORY = "2\tU2\t11/12/2019 6:11:30 PM\t\tN1-0\n"


def test_load_news_parses_and_validates(tmp_path):
    path = tmp_path / "news.tsv"
    path.write_text(NEWS_ROW + NEWS_ROW_NO_ABSTRACT)

    df = load_news(path)

    assert len(df) == 2
    assert df.loc[0, "news_id"] == "N1"
    assert pd.isna(df.loc[1, "abstract"])


def test_load_behaviors_parses_time_and_allows_null_history(tmp_path):
    path = tmp_path / "behaviors.tsv"
    path.write_text(BEHAVIORS_ROW + BEHAVIORS_ROW_NO_HISTORY)

    df = load_behaviors(path)

    assert len(df) == 2
    assert df.loc[0, "time"] == pd.Timestamp("2019-11-11 09:05:58")
    assert pd.isna(df.loc[1, "history"])


def test_validate_news_rejects_duplicate_news_id():
    df = pd.DataFrame(
        {
            "news_id": ["N1", "N1"],
            "category": ["a", "a"],
            "subcategory": ["b", "b"],
            "title": ["t1", "t2"],
            "abstract": ["x", "x"],
            "url": ["u", "u"],
            "title_entities": ["[]", "[]"],
            "abstract_entities": ["[]", "[]"],
        }
    )
    with pytest.raises(SchemaError):
        validate_news(df)


def test_explode_impressions_one_row_per_candidate_item(tmp_path):
    path = tmp_path / "behaviors.tsv"
    path.write_text(BEHAVIORS_ROW)  # "N1-1 N2-0" -> two candidate items
    behaviors = load_behaviors(path)

    exploded = explode_impressions(behaviors)

    assert len(exploded) == 2
    assert set(exploded["news_id"]) == {"N1", "N2"}
    clicked_by_item = dict(zip(exploded["news_id"], exploded["clicked"], strict=True))
    assert clicked_by_item == {"N1": 1, "N2": 0}
    assert (exploded["user_id"] == "U1").all()


def test_validate_behaviors_rejects_null_user_id():
    df = pd.DataFrame(
        {
            "impression_id": [1],
            "user_id": [None],
            "time": [pd.Timestamp.now()],
            "history": ["N1"],
            "impressions": ["N1-1"],
        }
    )
    with pytest.raises(SchemaError):
        validate_behaviors(df)
