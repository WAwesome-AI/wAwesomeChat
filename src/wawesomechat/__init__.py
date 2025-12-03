"""Core package for the wAwesomeChat experience."""

from __future__ import annotations

from .config import DatabaseSettings, Settings, load_environment, settings_from_env
from .storage import ChatStorage, CredentialRecord, ProviderRecord
from .multiaiproxy import UnifiedAIProvider, multiaiproxy

# Optional UI helpers; guard to avoid import errors in minimal environments.
try:  # pragma: no cover - optional
    from .app import get_modules_path, launch_app
except Exception:  # pragma: no cover - keep package importable even if app.py missing
    get_modules_path = None  # type: ignore
    launch_app = None  # type: ignore
try:  # pragma: no cover - optional heavy deps
    from .chat import WAwesomeChat
except Exception:  # pragma: no cover
    WAwesomeChat = None  # type: ignore

# Load environment variables on import so CLI experiments pick up .env seamlessly.
load_environment()

__all__ = [
    "ChatStorage",
    "CredentialRecord",
    "DatabaseSettings",
    "ProviderRecord",
    "Settings",
    "UnifiedAIProvider",
    "WAwesomeChat",
    "get_modules_path",
    "launch_app",
    "load_environment",
    "multiaiproxy",
    "settings_from_env",
]
