from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NETCARE_", extra="ignore")

    env: str = "development"
    # PostgreSQL is the supported production database. SQLite is allowed for local dev/tests only.
    database_url: str = "sqlite:///./netcare_dev.db"
    secret_key: str = "dev-only-change-me-dev-only-change-me"
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_production(self) -> None:
        if self.env == "production":
            if self.secret_key.startswith("dev-only") or len(self.secret_key) < 32:
                raise RuntimeError("NETCARE_SECRET_KEY must be set to a strong value in production")
            if self.database_url.startswith("sqlite"):
                raise RuntimeError("SQLite is not supported in production; use PostgreSQL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
