"""Centralized configuration helpers for wAwesomeChat."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - Pyodide: no filesystem .env to read
    # This module is imported in the browser too (chat.py -> config, and via
    # provider_catalog for the UI's default catalog). python-dotenv is a
    # server-side convenience with nothing to do there, so degrade to a no-op
    # rather than forcing a pointless micropip install. load_environment()
    # already guards on the file existing.
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def load_environment(env_file: str | os.PathLike[str] | None = None, *, override: bool = False) -> Path:
    candidate = Path(env_file or os.getenv("WA_ENV_FILE", DEFAULT_ENV_FILE))
    if candidate.exists():
        load_dotenv(candidate, override=override)
    return candidate


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _parse_float(value: Optional[str], default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def build_default_sqlite_url(filename: str | os.PathLike[str] = "wawesomechat.db") -> str:
    path = Path(filename)
    if not path.is_absolute():
        path = PACKAGE_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


@dataclass(slots=True)
class DatabaseSettings:
    url: str
    echo: bool = False
    pool_size: Optional[int] = None

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    def connect_args(self) -> Dict[str, Any]:
        if self.is_sqlite:
            return {"check_same_thread": False}
        return {}


@dataclass(slots=True)
class Settings:
    database: DatabaseSettings
    default_model: str
    request_timeout: float
    provider_config: Dict[str, Any]


def database_settings_from_env(env_file: str | os.PathLike[str] | None = None) -> DatabaseSettings:
    load_environment(env_file)
    url = os.getenv("WA_DB_URL")
    if not url:
        sqlite_file = os.getenv("WA_DB_FILE", "wawesomechat.db")
        url = build_default_sqlite_url(sqlite_file)
    echo = _parse_bool(os.getenv("WA_DB_ECHO"), default=False)
    pool_size = _parse_int(os.getenv("WA_DB_POOL_SIZE"))
    return DatabaseSettings(url=url, echo=echo, pool_size=pool_size)


def settings_from_env(env_file: str | os.PathLike[str] | None = None) -> Settings:
    load_environment(env_file)
    database = database_settings_from_env(env_file)
    default_model = os.getenv("WA_DEFAULT_MODEL", "gpt-4o-mini")
    request_timeout = _parse_float(os.getenv("WA_REQUEST_TIMEOUT"), default=60.0)
    provider_config: Dict[str, Any] = {}
    raw_provider = os.getenv("WA_PROVIDER_CONFIG")
    if raw_provider:
        try:
            provider_config = json.loads(raw_provider)
        except json.JSONDecodeError:
            print("[wawesomechat] Invalid JSON in WA_PROVIDER_CONFIG; falling back to defaults.")
    return Settings(
        database=database,
        default_model=default_model,
        request_timeout=request_timeout,
        provider_config=provider_config,
    )


__all__ = [
    "DatabaseSettings",
    "Settings",
    "build_default_sqlite_url",
    "database_settings_from_env",
    "load_environment",
    "settings_from_env",
]
