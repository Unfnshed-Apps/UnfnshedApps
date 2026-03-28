"""Application configuration using environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://nesting_user:nesting_secure_2024@localhost:5432/nesting_db"

    # API Security
    api_keys: str = ""  # Comma-separated list of valid API keys

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # CORS
    cors_origins: str = "*"  # Comma-separated allowed origins; override via CORS_ORIGINS env var

    # File Storage
    file_storage_path: str = "/var/lib/unfnshed/files"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def api_key_list(self) -> list[str]:
        """Parse comma-separated API keys into a list."""
        if not self.api_keys:
            return []
        return [key.strip() for key in self.api_keys.split(",") if key.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
