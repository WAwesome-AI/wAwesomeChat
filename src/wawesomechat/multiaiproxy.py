"""Backend-for-frontend proxy for multi-provider AI chat APIs."""

from __future__ import annotations

import json
import os
import copy

import litellm
from dotenv import load_dotenv
from pytincture.dataclass import backend_for_frontend, bff_stream

try:
    from .config import settings_from_env
    from .provider_catalog import DEFAULT_PROVIDER_CATALOG, DEFAULT_PROVIDER_SCHEMAS, DEFAULT_PROVIDER_SECRETS
    from .storage import ChatStorage
except ImportError:
    from config import settings_from_env
    from provider_catalog import DEFAULT_PROVIDER_CATALOG, DEFAULT_PROVIDER_SCHEMAS, DEFAULT_PROVIDER_SECRETS
    from storage import ChatStorage

load_dotenv()
litellm._turn_on_debug()

# WA_DEFAULT_MODEL is the documented setting (.env.example, config.py, README);
# DEFAULT_MODEL is kept as a fallback for older environments.
DEFAULT_MODEL = os.getenv("WA_DEFAULT_MODEL") or os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "60"))

def _parse_config(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray, memoryview)):
        try:
            raw = bytes(raw).decode()
        except Exception:
            return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


class UnifiedAIProvider:
    """Unified AI provider using LiteLLM for multi-provider support."""

    def __init__(self, provider_config):
        self.provider_config = provider_config or {"providers": {}}
        self.setup_environment()
        self._build_model_mapping()

    @staticmethod
    def setup_environment() -> None:
        env_mappings = {
            "OPENAI_API_KEY": "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
            "GOOGLE_KEY": "GEMINI_API_KEY",
            "XAI_API_KEY": "XAI_API_KEY",
            "AWS_ACCESS_KEY_ID": "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY": "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION": "AWS_DEFAULT_REGION",
        }
        for source_var, target_var in env_mappings.items():
            value = os.getenv(source_var)
            if value and not os.getenv(target_var):
                os.environ[target_var] = value

    def _build_model_mapping(self):
        providers = self.provider_config.get("providers", {})
        self.model_mapping = {}

        bedrock = providers.get("aws_bedrock", {})
        for provider_type, models in bedrock.items():
            for model in models:
                self.model_mapping[model] = model

        for provider, models in providers.items():
            if provider == "aws_bedrock":
                continue
            for model in models:
                self.model_mapping[model] = self._map_direct_model(provider, model)

    @staticmethod
    def _map_direct_model(provider, model):
        if provider in {"openai", "xai"}:
            return model
        if provider == "google":
            return f"gemini/{model}"
        return f"{provider}/{model}"

    def get_litellm_model(self, model):
        return self.model_mapping.get(model, model)

    def is_xai_model(self, model):
        providers = self.provider_config.get("providers", {})
        if model.startswith("xai/"):
            return True
        return model in providers.get("xai", []) or model.startswith("grok")

    def stream_completion(self, model, messages, **kwargs):
        if litellm is None:
            raise RuntimeError("litellm is required to stream completions")
        litellm_model = self.get_litellm_model(model)

        if self.is_xai_model(model):
            original_base_url = os.getenv("OPENAI_BASE_URL")
            os.environ["OPENAI_BASE_URL"] = "https://api.x.ai/v1"
            try:
                response = litellm.completion(
                    model=litellm_model,
                    messages=list(messages),
                    stream=True,
                    api_key=os.getenv("XAI_API_KEY"),
                    **kwargs,
                )
                for chunk in response:
                    yield chunk
            finally:
                if original_base_url is not None:
                    os.environ["OPENAI_BASE_URL"] = original_base_url
                elif "OPENAI_BASE_URL" in os.environ:
                    del os.environ["OPENAI_BASE_URL"]
        else:
            response = litellm.completion(
                model=litellm_model,
                messages=list(messages),
                stream=True,
                **kwargs,
            )
            for chunk in response:
                yield chunk


@backend_for_frontend
class multiaiproxy:
    """Multi-provider AI proxy supporting OpenAI, Anthropic, Bedrock, xAI, and Google."""

    def __init__(self, *, provider_config=None, default_model=None, timeout=None):
        self._storage = None
        self._storage_error = None
        config = (
            provider_config
            or self._load_config_from_env()
            or self._load_config_from_storage()
            or {"providers": copy.deepcopy(DEFAULT_PROVIDER_CATALOG)}
        )
        if not isinstance(config, dict):
            config = {"providers": copy.deepcopy(DEFAULT_PROVIDER_CATALOG)}
        providers_cfg = config.get("providers") if isinstance(config, dict) else None
        if not providers_cfg:
            config = {"providers": copy.deepcopy(DEFAULT_PROVIDER_CATALOG)}
        self._provider_config = config
        self._apply_provider_secrets(config)
        self._provider = UnifiedAIProvider(config)
        self._default_model = default_model or DEFAULT_MODEL
        self._timeout = timeout or REQUEST_TIMEOUT

    @staticmethod
    def _load_config_from_env():
        raw = os.getenv("MULTIPROXY_PROVIDER_CONFIG")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print("Warning: MULTIPROXY_PROVIDER_CONFIG is not valid JSON; falling back to defaults.")
            return None

    def _load_config_from_storage(self):
        store = self._get_storage()
        if not store:
            return None
        try:
            catalog = store.provider_catalog()
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"[multiaiproxy] Unable to load provider catalog: {exc}")
            return None
        if not catalog:
            return None
        merged = {}
        merged.update(catalog)
        return {"providers": merged}

    def _apply_provider_secrets(self, config):
        store = self._get_storage()
        if not store:
            return
        providers = store.list_providers() or []
        if not providers:
            return
        for record in providers:
            cfg = _parse_config(getattr(record, "config", None))
            secrets = cfg.get("secrets") or DEFAULT_PROVIDER_SECRETS.get(record.slug) or {}
            provider_type = cfg.get("type") or record.slug
            schema = DEFAULT_PROVIDER_SCHEMAS.get(provider_type) or DEFAULT_PROVIDER_SCHEMAS.get(record.slug)
            credentials = schema.get("credentials", {}) if schema else {}
            key_to_env = {val: key for key, val in credentials.items() if isinstance(val, str)}
            for key_name, source_env in secrets.items():
                target_env = key_to_env.get(key_name)
                if not target_env:
                    continue
                value = os.getenv(source_env)
                if value and not os.getenv(target_env):
                    os.environ[target_env] = value

    # ------------------------------------------------------------------ Provider metadata helpers

    def _get_storage(self):
        if self._storage_error:
            return None
        if self._storage is not None:
            return self._storage
        if ChatStorage is None:
            self._storage_error = "ChatStorage unavailable"
            return None
        try:
            settings = settings_from_env()
            self._storage = ChatStorage(settings.database)
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"[multiaiproxy] Unable to initialise storage: {exc}")
            self._storage_error = str(exc)
            self._storage = None
        return self._storage

    def get_provider_snapshot(self):
        store = self._get_storage()
        providers = []
        catalog = None
        if store:
            try:
                providers = self._serialize_providers(store.list_providers())
                catalog = store.provider_catalog()
            except Exception as exc:  # pragma: no cover - diagnostics only
                print(f"[multiaiproxy] Unable to load providers: {exc}")
        else:
            catalog = copy.deepcopy(self._provider_config.get("providers", {}))
            providers = self._serialize_config_providers(self._provider_config)
        if not catalog and providers:
            catalog = self._catalog_from_providers(providers)
        if not catalog:
            catalog = copy.deepcopy(self._provider_config.get("providers", {}))
        return {"providers": providers, "catalog": catalog or copy.deepcopy(DEFAULT_PROVIDER_CATALOG)}

    def save_provider(self, payload):
        store = self._get_storage()
        slug = payload.get("slug")
        if not slug:
            raise ValueError("slug is required")
        title = payload.get("title") or slug
        service = payload.get("service") or slug
        region = payload.get("region")
        config = {
            "status": payload.get("status"),
            "pill": payload.get("pill"),
            "iconClass": payload.get("iconClass"),
        }
        models = payload.get("models")
        if models is not None:
            config["models"] = models
        for key in ("type", "secrets", "settings"):
            value = payload.get(key)
            if value:
                config[key] = value
        providers_cfg = self._provider_config.setdefault("providers", {})
        providers_cfg[slug] = config.get("models") if "models" in config else providers_cfg.get(slug, [])
        if not store:
            return self.get_provider_snapshot()
        try:
            store.upsert_provider(
                slug=slug,
                title=title,
                service=service,
                region=region,
                config=config,
            )
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"[multiaiproxy] Unable to save provider '{slug}': {exc}")
        return self.get_provider_snapshot()

    def delete_provider(self, payload):
        store = self._get_storage()
        if not store:
            return self.get_provider_snapshot()
        slug = payload.get("slug") if isinstance(payload, dict) else payload
        if not slug:
            raise ValueError("slug is required")
        try:
            store.delete_provider(slug)
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"[multiaiproxy] Unable to delete provider '{slug}': {exc}")
        return self.get_provider_snapshot()

    def _serialize_providers(self, records):
        serialized = []
        for record in records or []:
            cfg = _parse_config(getattr(record, "config", None))
            serialized.append(
                {
                    "slug": record.slug,
                    "title": record.title,
                    "service": record.service,
                    "region": record.region,
                    "status": cfg.get("status"),
                    "pill": cfg.get("pill"),
                    "iconClass": cfg.get("iconClass"),
                    "models": cfg.get("models"),
                    "secrets": cfg.get("secrets"),
                    "type": cfg.get("type") or cfg.get("provider_type"),
                    "settings": cfg.get("settings"),
                }
            )
        return serialized

    @staticmethod
    def _catalog_from_providers(providers):
        catalog = {}
        for item in providers or []:
            slug = item.get("slug")
            if not slug:
                continue
            models = item.get("models")
            if models:
                catalog[slug] = models
        return catalog

    @staticmethod
    def _serialize_config_providers(provider_config):
        providers_cfg = provider_config.get("providers", {}) if isinstance(provider_config, dict) else {}
        serialized = []
        for slug, models in providers_cfg.items():
            serialized.append({"slug": slug, "models": models, "title": slug, "service": slug, "type": slug})
        return serialized

    def get_default_model(self):
        """The model the UI should select before the user has picked one.

        Browser-side code cannot read this from the environment -- os.environ is
        empty in Pyodide -- so it has to come across the BFF boundary.
        """
        return self._default_model

    def get_available_models(self):
        return (self._provider_config or DEFAULT_PROVIDER_CONFIG).get("providers", {})

    def get_model_info(self, model):
        litellm_name = self._provider.get_litellm_model(model)
        provider = "unknown"
        providers = self._provider_config.get("providers", {})

        if model in providers.get("openai", []):
            provider = "openai"
        elif model in providers.get("anthropic", []):
            provider = "anthropic"
        elif model in providers.get("xai", []):
            provider = "xai"
        elif model in providers.get("google", []):
            provider = "google"
        elif any(model in group for group in providers.get("aws_bedrock", {}).values()):
            provider = "aws_bedrock"

        return {
            "original_name": model,
            "litellm_name": litellm_name,
            "provider": provider,
            "supported": model in self._provider.model_mapping,
        }

    @bff_stream()
    def chat_stream(self, messages, model=None, **extra):
        options = extra.copy()
        timeout_override = options.pop("timeout", None)
        options.pop("stream", None)
        timeout = timeout_override or self._timeout

        selected_model = model or self._default_model

        if selected_model not in self._provider.model_mapping:
            raise ValueError(
                f"Model '{selected_model}' is not supported. Available models: {list(self._provider.model_mapping.keys())}"
            )

        try:
            for chunk in self._provider.stream_completion(
                model=selected_model,
                messages=messages,
                timeout=timeout,
                **options,
            ):
                if hasattr(chunk, "model_dump"):
                    yield chunk.model_dump(exclude_none=True)
                elif hasattr(chunk, "dict"):
                    yield chunk.dict(exclude_none=True)
                else:
                    yield chunk
        except Exception as exc:  # pragma: no cover - provider errors
            yield {
                "error": {
                    "message": str(exc),
                    "type": "provider_error",
                    "code": "stream_error",
                }
            }

    @bff_stream()
    def chat_stream_with_provider_info(self, messages, model=None, **extra):
        model_info = self.get_model_info(model or self._default_model)
        yield {"type": "model_info", "model_info": model_info}
        for chunk in self.chat_stream(messages, model, **extra):
            if isinstance(chunk, dict) and "error" not in chunk:
                chunk["provider"] = model_info["provider"]
            yield chunk


__all__ = ["multiaiproxy", "UnifiedAIProvider"]
