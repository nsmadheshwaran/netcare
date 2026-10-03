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
    # Business-local time for "today" and report dates. India has no DST, so a fixed offset is exact.
    utc_offset_minutes: int = 330
    # Uploaded documents live on disk here, outside the web root. Back this directory up with the database.
    storage_dir: str = "./storage"
    max_upload_mb: int = 15
    org_storage_quota_mb: int = 2048
    # Notifications. Email is sent only when smtp_host and smtp_from are set.
    notifications_worker: bool = True  # background thread: daily digests and email delivery, every minute
    app_url: str = ""  # public URL used in email links, e.g. https://netcare.example.com
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

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
