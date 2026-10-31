from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINNE_", env_file=".env")

    database_url: str = "postgresql+psycopg://minne:minne@localhost:5432/minne"
    raw_dir: Path = Path("knowledge/raw")
    user_agent: str = "MinneMinne/0.1 (personal knowledge archive)"
    poll_seconds: int = Field(default=30, ge=1)


settings = Settings()
