from recommender.serving.config import Settings


def test_settings_default_to_the_existing_localhost_redis_url():
    settings = Settings(_env_file=None)

    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.api_port == 8000
    assert settings.redis_password is None


def test_redis_url_with_auth_is_unchanged_when_no_password_is_set():
    settings = Settings(_env_file=None)

    assert settings.redis_url_with_auth() == settings.redis_url


def test_redis_url_with_auth_weaves_in_a_real_password():
    settings = Settings(_env_file=None, redis_password="hunter2")

    assert settings.redis_url_with_auth() == "redis://:hunter2@localhost:6379/0"


def test_secret_value_never_appears_in_repr_or_str():
    settings = Settings(_env_file=None, redis_password="hunter2")

    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings)


def test_redis_url_with_auth_percent_encodes_a_password_with_uri_significant_characters():
    """Regression test for a real bug, found by audit: an unencoded
    password containing a URI-significant character corrupts the
    resulting URL rather than raising anywhere the mistake could be
    seen -- e.g. a `/` in the password gets parsed as the start of the
    URL's path, leaving hostname and password both `None` to any URL
    parser, including redis-py's own `from_url`. Fails on the pre-fix
    code (the raw `/` breaks parsing) and passes once the password is
    percent-encoded before being woven into the URL.
    """
    from urllib.parse import unquote, urlsplit

    settings = Settings(_env_file=None, redis_password="p/ss@w:ord")

    url = settings.redis_url_with_auth()
    parsed = urlsplit(url)

    assert parsed.hostname == "localhost"
    assert parsed.password is not None
    assert unquote(parsed.password) == "p/ss@w:ord"
