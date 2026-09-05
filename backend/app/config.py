from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_CORS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://mplad:mplad@localhost:5432/mplad"
    data_dir: str = "../data"

    # Frontend origins allowed to call the API. Set CORS_ORIGINS to a
    # comma-separated list in production (e.g. "https://foo.vercel.app").
    cors_origins: list[str] = _DEFAULT_CORS

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()] or _DEFAULT_CORS
        return v


settings = Settings()
