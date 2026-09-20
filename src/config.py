"""Load and validate project configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


class CohortConfig(BaseModel):
    steamspy_tag: str = "Horror"
    release_date_min: str = "2020-01-01"
    require_horror_signal: bool = True
    horror_tag_max_rank: int = 3
    horror_tag_min_vote_ratio: float = 0.35
    subtags: List[str] = Field(default_factory=list)


class ModelConfig(BaseModel):
    version: str = "v1.0.0"
    review_multiplier: float = 40.0
    net_revenue_factor: float = 0.70
    review_proxy_uncertainty: float = 0.50
    indie_max_reviews: int = 50000
    aaa_min_reviews: int = 100000


class RateLimitConfig(BaseModel):
    steamspy_requests_per_second: float = 1.0
    steam_store_requests_per_second: float = 2.0
    steam_store_batch_pause_seconds: float = 0.5


class PathsConfig(BaseModel):
    database: str = "data/horror_index.sqlite3"
    cache_dir: str = "data/cache"

    def database_path(self) -> Path:
        path = Path(self.database)
        if not path.is_absolute():
            path = ROOT / path
        return path

    def cache_path(self) -> Path:
        path = Path(self.cache_dir)
        if not path.is_absolute():
            path = ROOT / path
        return path


class AppConfig(BaseModel):
    cohort: CohortConfig = Field(default_factory=CohortConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    major_publishers: List[str] = Field(default_factory=list)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    steam_web_api_key: str = ""


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return AppConfig.model_validate(raw)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()


@lru_cache(maxsize=1)
def get_env() -> EnvSettings:
    return EnvSettings()
