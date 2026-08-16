import pandas as pd

from recommender.data.analytics import click_rate_by_category


def test_click_rate_by_category(tmp_path):
    split_dir = tmp_path / "toy"
    split_dir.mkdir()

    news = pd.DataFrame(
        {
            "news_id": ["N1", "N2", "N3"],
            "category": ["sports", "sports", "news"],
            "subcategory": ["a", "a", "b"],
            "title": ["t1", "t2", "t3"],
            "abstract": ["x", "x", "x"],
            "url": ["u", "u", "u"],
            "title_entities": ["[]", "[]", "[]"],
            "abstract_entities": ["[]", "[]", "[]"],
        }
    )
    news.to_parquet(split_dir / "news.parquet", index=False)

    behaviors = pd.DataFrame(
        {
            "impression_id": [1, 2],
            "user_id": ["U1", "U2"],
            "time": [pd.Timestamp.now(), pd.Timestamp.now()],
            "history": [None, None],
            "impressions": ["N1-1 N2-0", "N3-0"],
        }
    )
    behaviors.to_parquet(split_dir / "behaviors.parquet", index=False)

    result = click_rate_by_category("toy", processed_dir=tmp_path).set_index("category")

    assert result.loc["sports", "impressions"] == 2
    assert result.loc["sports", "clicks"] == 1
    assert result.loc["sports", "ctr"] == 0.5
    assert result.loc["news", "impressions"] == 1
    assert result.loc["news", "clicks"] == 0
    assert result.loc["news", "ctr"] == 0.0
    # sports has the higher CTR, so it should rank first
    assert result.loc["sports", "ctr_rank"] == 1
