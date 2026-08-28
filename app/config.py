"""Runtime configuration, loaded from environment variables (BS_* prefix)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BS_", env_file=None, extra="ignore")

    tz: str = "Europe/London"
    auth_token: str = ""
    external_lookup: str = "off"
    warn_days: List[int] = Field(default_factory=lambda: [30, 90])
    default_location: str = "pantry"
    data_dir: Path = Path("/data")
    backup_retention: int = 30

    @field_validator("warn_days", mode="before")
    @classmethod
    def _coerce_warn_days(cls, v):
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    @property
    def products_path(self) -> Path:
        return self.data_dir / "products.json"

    @property
    def stock_path(self) -> Path:
        return self.data_dir / "stock.json"

    @property
    def sessions_path(self) -> Path:
        return self.data_dir / "sessions.json"

    @property
    def notifications_path(self) -> Path:
        return self.data_dir / "notifications.json"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "audit.jsonl"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.data_dir.mkdir(parents=True, exist_ok=True)
        _settings.backups_dir.mkdir(parents=True, exist_ok=True)
    return _settings
