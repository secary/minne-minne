from dataclasses import dataclass
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    url: str
    root_path: str
    enabled: bool = True
    interval_months: int = 1
    max_pages: int = 1000
    max_depth: int = 2
    delay_seconds: int = 3


# 修改来源后重启 API 和 Worker；默认抓取参数仅用于新建来源。
CRAWL_SOURCES = (
    SourceConfig(
        id="wikiwiki-kancolle",
        name="艦これ攻略 Wiki",
        url="https://wikiwiki.jp/kancolle/",
        root_path="/kancolle/",
    ),
    SourceConfig(
        id="kcwiki-zh",
        name="舰娘百科",
        url="https://zh.kcwiki.cn/wiki/%E8%88%B0%E5%A8%98%E7%99%BE%E7%A7%91",
        root_path="/wiki/",
    ),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINNE_", env_file=".env")

    database_url: str = "postgresql+psycopg://minne:minne@localhost:5432/minne"
    raw_dir: Path = Path("knowledge/raw")
    user_agent: str = "MinneMinne/0.1 (personal knowledge archive)"
    poll_seconds: int = Field(default=30, ge=1)


settings = Settings()
