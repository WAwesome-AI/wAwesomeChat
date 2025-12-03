"""Persistence helpers for chat transcripts."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime
import traceback


try:
    from sqlalchemy import (
        Boolean,
        Column,
        DateTime,
        ForeignKey,
        Integer,
        MetaData,
        String,
        Table,
        Text,
        UniqueConstraint,
        create_engine,
        insert,
        select,
        update,
        func,
    )
except Exception as exc:  # pragma: no cover - optional dependency
    SQLALCHEMY_AVAILABLE = False
    SQLALCHEMY_IMPORT_ERROR = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
else:
    SQLALCHEMY_AVAILABLE = True
    SQLALCHEMY_IMPORT_ERROR = None

try:
    from .config import DatabaseSettings, load_environment
    from .provider_catalog import DEFAULT_PROVIDER_SCHEMAS, DEFAULT_PROVIDER_SECRETS
except ImportError:
    from config import DatabaseSettings, load_environment
    from provider_catalog import DEFAULT_PROVIDER_SCHEMAS, DEFAULT_PROVIDER_SECRETS

def _env_truthy(key, default=False):
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _schema_config_payload(slug: str, schema: dict) -> dict:
    """Build a serializable provider config from a schema entry."""
    base_config = schema.get("config") or {}
    config = copy.deepcopy(base_config) if isinstance(base_config, dict) else {}
    provider_type = schema.get("provider_type") or slug
    if provider_type:
        config.setdefault("type", provider_type)
    secrets = DEFAULT_PROVIDER_SECRETS.get(slug) or {}
    if secrets and "secrets" not in config:
        config["secrets"] = secrets
    settings = {}
    if schema.get("region"):
        settings["region"] = schema["region"]
    if settings:
        config.setdefault("settings", settings)
    return config


if SQLALCHEMY_AVAILABLE:
    metadata = MetaData()

    chat_messages = Table(
        "chat_messages",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("session_id", String(64), nullable=False),
        Column("role", String(32), nullable=False),
        Column("content", Text, nullable=False),
        Column("model", String(64), nullable=True),
        Column("provider", String(32), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    providers = Table(
        "providers",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("slug", String(64), nullable=False, unique=True),
        Column("title", String(128), nullable=False),
        Column("service", String(64), nullable=False),
        Column("region", String(32), nullable=True),
        Column("config", Text, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    )

    provider_credentials = Table(
        "provider_credentials",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("provider_id", ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        Column("key_name", String(64), nullable=False),
        Column("key_value", Text, nullable=False),
        Column("is_secret", Boolean, nullable=False, server_default="1"),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        UniqueConstraint("provider_id", "key_name", name="uq_provider_key"),
    )
else:
    metadata = None
    chat_messages = None
    providers = None
    provider_credentials = None


@dataclass(slots=True)
class MessageRecord:
    id: int
    session_id: str
    role: str
    content: str
    model: str | None
    provider: str | None
    created_at: datetime


@dataclass(slots=True)
class ProviderRecord:
    id: int
    slug: str
    title: str
    service: str
    region: str | None
    config: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class CredentialRecord:
    id: int
    provider_id: int
    key_name: str
    key_value: str
    is_secret: bool
    created_at: datetime | None = None


if SQLALCHEMY_AVAILABLE:

    class ChatStorage:
        """Thin repository for chats, providers, and credentials."""

        def __init__(self, settings):
            self.settings = settings
            self.engine = self._build_engine()
            metadata.create_all(self.engine)
            if _env_truthy("WA_SEED_PROVIDERS"):
                self.seed_from_environment(force=_env_truthy("WA_SEED_FORCE"))

        def _build_engine(self):
            kwargs = {"future": True, "echo": self.settings.echo}
            connect_args = self.settings.connect_args()
            if connect_args:
                kwargs["connect_args"] = connect_args
            if self.settings.pool_size is not None:
                kwargs["pool_size"] = self.settings.pool_size
            return create_engine(self.settings.url, **kwargs)

        def record_message(
            self,
            *,
            session_id,
            role,
            content,
            model=None,
            provider=None,
        ):
            with self.engine.begin() as conn:
                conn.execute(
                    insert(chat_messages).values(
                        session_id=session_id,
                        role=role,
                        content=content,
                        model=model,
                        provider=provider,
                    )
                )

        def history(self, session_id, limit=50):
            stmt = (
                select(chat_messages)
                .where(chat_messages.c.session_id == session_id)
                .order_by(chat_messages.c.created_at.desc())
                .limit(limit)
            )
            with self.engine.begin() as conn:
                rows = conn.execute(stmt).fetchall()
            return [MessageRecord(**row._mapping) for row in rows]

        def upsert_provider(
            self,
            *,
            slug,
            title,
            service,
            region=None,
            config=None,
        ):
            serialized_config = json.dumps(config or {}) if config else None
            with self.engine.begin() as conn:
                existing = conn.execute(select(providers.c.id).where(providers.c.slug == slug)).scalar_one_or_none()
                if existing:
                    conn.execute(
                        update(providers)
                        .where(providers.c.id == existing)
                        .values(title=title, service=service, region=region, config=serialized_config)
                    )
                    return existing
                result = conn.execute(
                    insert(providers).values(
                        slug=slug,
                        title=title,
                        service=service,
                        region=region,
                        config=serialized_config,
                    )
                )
                provider_id = result.inserted_primary_key[0]
            return provider_id

        def set_provider_secret(self, provider_id, key_name, key_value, *, is_secret=True):
            with self.engine.begin() as conn:
                existing = conn.execute(
                    select(provider_credentials.c.id).where(
                        (provider_credentials.c.provider_id == provider_id)
                        & (provider_credentials.c.key_name == key_name)
                    )
                ).scalar_one_or_none()
                if existing:
                    conn.execute(
                        update(provider_credentials)
                        .where(provider_credentials.c.id == existing)
                        .values(key_value=key_value, is_secret=is_secret)
                    )
                else:
                    conn.execute(
                        insert(provider_credentials).values(
                            provider_id=provider_id,
                            key_name=key_name,
                            key_value=key_value,
                            is_secret=is_secret,
                        )
                    )

        def list_providers(self):
            with self.engine.begin() as conn:
                rows = conn.execute(select(providers)).fetchall()
            return [ProviderRecord(**row._mapping) for row in rows]

        def list_credentials(self, provider_id):
            with self.engine.begin() as conn:
                rows = conn.execute(
                    select(provider_credentials).where(provider_credentials.c.provider_id == provider_id)
                ).fetchall()
            return [CredentialRecord(**row._mapping) for row in rows]

        def provider_catalog(self):
            """Return provider->models catalog stored in provider configs."""
            catalog = {}
            for provider in self.list_providers():
                raw_config = provider.config
                if not raw_config or not str(raw_config).strip():
                    continue
                config = None
                if isinstance(raw_config, (bytes, bytearray, memoryview)):
                    try:
                        raw_config = bytes(raw_config).decode()
                    except Exception:
                        raw_config = None
                if isinstance(raw_config, dict):
                    config = raw_config
                elif raw_config:
                    try:
                        config = json.loads(raw_config)
                    except (json.JSONDecodeError, TypeError):
                        config = None
                if isinstance(config, dict) and "models" in config:
                    catalog[provider.slug] = config.get("models")
            return catalog

        def seed_from_environment(self, *, force=False, include_services=None):
            load_environment()
            services = include_services or DEFAULT_PROVIDER_SCHEMAS.keys()
            for slug in services:
                schema = DEFAULT_PROVIDER_SCHEMAS.get(slug)
                if not schema:
                    continue
                region = schema.get("region")
                if slug == "aws_bedrock":
                    region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
                provider_id = self.upsert_provider(
                    slug=slug,
                    title=schema["title"],
                    service=schema["service"],
                    region=region,
                    config=_schema_config_payload(slug, schema),
                )
                credentials = schema.get("credentials", {})
                if not credentials:
                    continue
                for env_var, key_name in credentials.items():
                    value = os.getenv(env_var)
                    if not value:
                        continue
                    if not force:
                        current = self.list_credentials(provider_id)
                        if any(cred.key_name == key_name for cred in current):
                            continue
                    self.set_provider_secret(provider_id, key_name=key_name, key_value=value)

        def delete_provider(self, slug: str):
            if not slug:
                return
            with self.engine.begin() as conn:
                conn.execute(providers.delete().where(providers.c.slug == slug))

else:  # pragma: no cover - Pyodide / environments without SQLAlchemy
    ChatStorage = None
