"""Provider catalog defaults sourced from SQLite; CSV is used only for initial seeding."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any

try:
    from .config import build_default_sqlite_url, settings_from_env
except ImportError:  # pragma: no cover - allow running as a script
    from config import build_default_sqlite_url, settings_from_env

try:
    import sqlite3  # type: ignore

    SQLITE_AVAILABLE = True
except Exception:  # pragma: no cover - pyodide/browser runtime
    sqlite3 = None  # type: ignore
    SQLITE_AVAILABLE = False

DATA_FILE = Path(__file__).resolve().parent / "data" / "seed_providers.csv"


def _with_models(models):
    return {"models": models}


def _parse_json_field(raw: Any, default):
    if raw is None or raw == "":
        return copy.deepcopy(default)
    if isinstance(raw, (list, dict)):
        return copy.deepcopy(raw)
    try:
        parsed = json.loads(raw)
    except Exception:
        return copy.deepcopy(default)
    return parsed if isinstance(parsed, (list, dict, str)) else copy.deepcopy(default)


def _parse_models(raw_models):
    models = _parse_json_field(raw_models, default=[])
    return models if isinstance(models, (list, dict)) else []


def _load_seed_rows():
    if not DATA_FILE.exists():
        return []
    rows = []
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    return rows


def _db_path():
    if not SQLITE_AVAILABLE:
        return None
    settings = settings_from_env()
    url = settings.database.url or build_default_sqlite_url()
    if not url.startswith("sqlite:///"):
        return None
    path = Path(url.replace("sqlite:///", "", 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_tables(conn: sqlite3.Connection):
    if not SQLITE_AVAILABLE:
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


def _load_rows_from_db():
    if not SQLITE_AVAILABLE:
        return []
    db_path = _db_path()
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return []
    conn.row_factory = sqlite3.Row
    try:
        _ensure_tables(conn)
        rows = conn.execute("SELECT slug, title, service, region, config FROM providers").fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    return rows


def _seed_db_from_csv(seed_rows):
    if not SQLITE_AVAILABLE:
        return
    db_path = _db_path()
    if not db_path:
        return
    try:
        conn = sqlite3.connect(db_path)
        _ensure_tables(conn)
    except Exception:
        return
    with conn:
        for row in seed_rows:
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            title = row.get("title") or slug.title()
            service = row.get("service") or slug
            region = row.get("region") or None
            models = _parse_models(row.get("models"))
            credentials = _parse_json_field(row.get("credentials"), default={})
            secrets = _secret_map(credentials if isinstance(credentials, dict) else {})
            cfg = {
                "models": models,
                "type": row.get("type") or slug,
                "secrets": secrets,
            }
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
                (slug, title, service, region, json.dumps(cfg)),
            )
        conn.commit()
    conn.close()


def _build_schemas_from_rows(rows):
    schemas = {}
    for row in rows:
        slug = (row.get("slug") or "").strip()
        if not slug:
            continue
        title = row.get("title") or slug.title()
        service = row.get("service") or slug
        region = row.get("region") or None
        provider_type = row.get("type") or slug
        models = _parse_models(row.get("models"))
        credentials = _parse_json_field(row.get("credentials"), default={})
        schema = {
            "title": title,
            "service": service,
            "region": region,
            "provider_type": provider_type,
            "config": _with_models(models),
            "credentials": credentials if isinstance(credentials, dict) else {},
        }
        schemas[slug] = schema
    return schemas


def _build_catalog_from_schemas(schemas):
    catalog = {}
    for slug, schema in schemas.items():
        if not slug or not isinstance(schema, dict):
            continue
        models = schema.get("config", {}).get("models")
        if models:
            catalog[slug] = copy.deepcopy(models)
    return catalog


def _secret_map(credentials: dict) -> dict:
    """Return a mapping of logical secret names to environment variables."""
    if not isinstance(credentials, dict):
        return {}
    return {value: key for key, value in credentials.items() if isinstance(value, str)}


def _schemas_from_db_rows(rows):
    schemas = {}
    for row in rows:
        slug = (row["slug"] or "").strip()
        if not slug:
            continue
        cfg = _parse_config(row["config"])
        schemas[slug] = {
            "title": row["title"] or slug.title(),
            "service": row["service"] or slug,
            "region": row["region"],
            "provider_type": cfg.get("type") or slug,
            "config": _with_models(cfg.get("models")),
            "credentials": cfg.get("credentials") or {},
            "secrets": cfg.get("secrets") or {},
        }
    return schemas


def _load_catalog_and_schemas():
    if not SQLITE_AVAILABLE:
        # In browser/pyodide we rely entirely on backend snapshots for data.
        seed_rows = _load_seed_rows()
        schemas = _build_schemas_from_rows(seed_rows)
        secrets = {slug: _secret_map(schema.get("credentials", {})) for slug, schema in schemas.items()}
        return {}, schemas, secrets, seed_rows
    seed_rows = _load_seed_rows()
    db_rows = _load_rows_from_db()
    if not db_rows and seed_rows and SQLITE_AVAILABLE:
        _seed_db_from_csv(seed_rows)
        db_rows = _load_rows_from_db()

    if db_rows:
        schemas = _schemas_from_db_rows(db_rows)
    else:
        schemas = _build_schemas_from_rows(seed_rows)

    catalog = _build_catalog_from_schemas(schemas)
    secrets = {
        slug: (schema.get("secrets") or _secret_map(schema.get("credentials", {}))) for slug, schema in schemas.items()
    }
    return catalog, schemas, secrets, seed_rows


DEFAULT_PROVIDER_CATALOG, DEFAULT_PROVIDER_SCHEMAS, DEFAULT_PROVIDER_SECRETS, DEFAULT_SEED_ROWS = _load_catalog_and_schemas()


__all__ = ["DEFAULT_PROVIDER_CATALOG", "DEFAULT_PROVIDER_SCHEMAS", "DEFAULT_PROVIDER_SECRETS", "DEFAULT_SEED_ROWS"]
