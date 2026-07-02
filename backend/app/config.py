from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/musically.db"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # File paths
    MUSIC_DIR: str = "/music"
    DOWNLOADS_DIR: str = "/downloads"
    CONFIG_DIR: str = "/config"

    # Security
    SECRET_KEY: str = "change-me-in-production"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.SECRET_KEY == "change-me-in-production":
            raise RuntimeError(
                "SECRET_KEY is still set to the default value. "
                "Set a strong random secret via the SECRET_KEY environment variable. "
                "Generate one with: openssl rand -hex 32"
            )

    # Environment
    ENVIRONMENT: str = "development"

    # External API credentials
    QOBUZ_EMAIL: str | None = None
    QOBUZ_PASSWORD: str | None = None
    LASTFM_API_KEY: str | None = None
    SPOTIFY_CLIENT_ID: str | None = None
    SPOTIFY_CLIENT_SECRET: str | None = None
    LASTFM_API_SECRET: str | None = None
    LASTFM_USERNAME: str | None = None
    SPOTIFY_REDIRECT_URI: str | None = None
    LOG_LEVEL: str = "info"
    DISCORD_WEBHOOK_URL: str | None = None

    # Server
    APP_PORT: int = 8000


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached settings instance, creating it if necessary."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
