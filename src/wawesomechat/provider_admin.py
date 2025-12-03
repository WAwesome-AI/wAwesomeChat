"""Minimal backend-for-frontend handler for providers/models using direct SQLite operations."""

from __future__ import annotations

import json
from pathlib import Path

from pytincture.dataclass import backend_for_frontend

try:
    from .config import settings_from_env, build_default_sqlite_url
except ImportError:  # pragma: no cover
    from config import settings_from_env, build_default_sqlite_url

try:
    import sqlite3  # type: ignore
except Exception:  # pragma: no cover - pyodide/browser runtime
    sqlite3 = None  # type: ignore


def _db_path_from_url(url: str) -> Path | None:
    if not url or not url.startswith("sqlite:///"):
        return None
    return Path(url.replace("sqlite:///", "", 1))


def _connect(db_path: Path):
    if sqlite3 is None:
        raise ImportError("sqlite3 not available in this runtime")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_tables(conn: sqlite3.Connection):
    if sqlite3 is None:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            service TEXT NOT NULL,
            region TEXT NULL,
            config TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()


def _parse_config(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


@backend_for_frontend
class provider_admin:
    def __init__(self):
        settings = settings_from_env()
        url = settings.database.url or build_default_sqlite_url()
        self.db_path = _db_path_from_url(url)

    # ---------------- public API ----------------

    def get_provider_snapshot(self):
        providers, catalog = self._load_providers_and_catalog()
        print("[provider_admin] snapshot providers", providers, "catalog keys", list(catalog.keys()))
        return {"providers": providers, "catalog": catalog}

    def save_provider(self, payload):
        if not self.db_path:
            return self.get_provider_snapshot()
        slug = (payload.get("slug") or "").strip()
        if not slug:
            raise ValueError("slug is required")
        existing = {}
        try:
            providers, catalog = self._load_providers_and_catalog()
            existing = next((p for p in providers if p.get("slug") == slug), {})
        except Exception:
            existing = {}
        title = payload.get("title") or slug
        service = payload.get("service") or slug
        region = payload.get("region")
        new_models = payload.get("models")
        current_models = existing.get("models") if isinstance(existing, dict) else None
        merged_models = new_models if new_models is not None else current_models
        config = {
            "status": payload.get("status") or existing.get("status"),
            "pill": payload.get("pill") or existing.get("pill"),
            "iconClass": payload.get("iconClass") or existing.get("iconClass"),
            "models": merged_models,
            "type": payload.get("type") or payload.get("provider_type") or existing.get("type") or slug,
            "secrets": payload.get("secrets") or existing.get("secrets"),
            "settings": payload.get("settings") or existing.get("settings"),
        }
        print("[provider_admin] save_provider db", self.db_path, "payload", payload)
        with _connect(self.db_path) as conn:
            _ensure_tables(conn)
            conn.execute(
                """
                INSERT INTO providers (slug, title, service, region, config)
                VALUES (?, ?, ?, ?, json(?))
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    service=excluded.service,
                    region=excluded.region,
                    config=excluded.config,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (slug, title, service, region, json.dumps(config)),
            )
            conn.commit()
        return self.get_provider_snapshot()

    def delete_provider(self, payload):
        if not self.db_path:
            return self.get_provider_snapshot()
        slug = payload.get("slug") if isinstance(payload, dict) else payload
        slug = (slug or "").strip()
        if not slug:
            raise ValueError("slug is required")
        print("[provider_admin] delete_provider db", self.db_path, "slug", slug)
        with _connect(self.db_path) as conn:
            _ensure_tables(conn)
            conn.execute("DELETE FROM providers WHERE slug = ?", (slug,))
            conn.commit()
        return self.get_provider_snapshot()

    # ---------------- internal helpers ----------------

    def _load_providers_and_catalog(self):
        providers = []
        catalog = {}
        if not self.db_path:
            return providers, catalog
        with _connect(self.db_path) as conn:
            _ensure_tables(conn)
            rows = conn.execute("SELECT slug, title, service, region, config FROM providers").fetchall()
        for row in rows:
            cfg = _parse_config(row["config"])
            providers.append(
                {
                    "slug": row["slug"],
                    "title": row["title"],
                    "service": row["service"],
                    "region": row["region"],
                    "status": cfg.get("status"),
                    "pill": cfg.get("pill"),
                    "iconClass": cfg.get("iconClass"),
                    "models": cfg.get("models"),
                    "secrets": cfg.get("secrets"),
                    "type": cfg.get("type") or cfg.get("provider_type"),
                    "settings": cfg.get("settings"),
                }
            )
            models = cfg.get("models")
            if models:
                catalog[row["slug"]] = models
        if not catalog:
            catalog = {}
        return providers, catalog
