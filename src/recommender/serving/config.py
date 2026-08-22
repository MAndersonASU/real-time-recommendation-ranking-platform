from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every environment-dependent setting the serving app reads,
    collected in one typed place instead of scattered `os.environ.get`
    calls. Every field has a safe local default, so running this project
    exactly as it always has (no Docker, no .env file) needs no
    configuration at all -- only a containerized or otherwise
    non-default deployment needs to actually set anything.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    redis_url: str = "redis://localhost:6379/0"
    redis_password: SecretStr | None = None
    api_port: int = 8000

    def redis_url_with_auth(self) -> str:
        """The real URL a Redis client should connect with -- if a
        password is set, it's woven into the connection string here,
        at the one point it's actually used, rather than being passed
        around as a plain string anywhere else in the app. `SecretStr`
        means the password itself never appears in a repr, a log line,
        or an accidental print -- str(settings) shows `**********`.
        """
        if self.redis_password is None:
            return self.redis_url
        scheme, _, rest = self.redis_url.partition("://")
        return f"{scheme}://:{self.redis_password.get_secret_value()}@{rest}"


def load_settings() -> Settings:
    return Settings()
