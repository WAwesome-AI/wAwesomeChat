import importlib.util
import sys
from pathlib import Path

import pytest

# Load modules directly to avoid optional UI deps pulled in by package __init__
ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = ROOT / "src" / "wawesomechat" / "storage.py"
CONFIG_PATH = ROOT / "src" / "wawesomechat" / "config.py"


def load_module(path: Path, name: str):
    path_parent = str(path.parent)
    if path_parent not in sys.path:
        sys.path.insert(0, path_parent)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)  # type: ignore
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore
    return module


storage = load_module(STORAGE_PATH, "wawesomechat_storage")
config_mod = load_module(CONFIG_PATH, "wawesomechat_config")
ChatStorage = storage.ChatStorage
DatabaseSettings = config_mod.DatabaseSettings


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setenv("WA_SEED_PROVIDERS", "0")
    db_file = tmp_path / "providers.db"
    settings = DatabaseSettings(url=f"sqlite:///{db_file}", echo=False, pool_size=None)
    return ChatStorage(settings)


def test_catalog_preserves_grouped_models(temp_store: ChatStorage, tmp_path):
    config = {
        "models": {
            "anthropic": ["bedrock/anthropic.claude-sonnet-4-test"],
            "amazon": ["bedrock/amazon.nova-micro-test"],
        },
        "type": "aws_bedrock",
    }
    temp_store.upsert_provider(
        slug="aws_bedrock",
        title="AWS Bedrock",
        service="aws_bedrock",
        region="us-east-1",
        config=config,
    )

    # Reopen the store to ensure persistence
    reopened = ChatStorage(DatabaseSettings(url=temp_store.engine.url.render_as_string(hide_password=False)))
    catalog = reopened.provider_catalog()
    assert "aws_bedrock" in catalog
    assert catalog["aws_bedrock"]["anthropic"] == ["bedrock/anthropic.claude-sonnet-4-test"]
    assert catalog["aws_bedrock"]["amazon"] == ["bedrock/amazon.nova-micro-test"]


def test_catalog_flat_models(temp_store: ChatStorage, tmp_path):
    config = {
        "models": ["gpt-5", "gpt-4o-mini"],
        "type": "openai",
    }
    temp_store.upsert_provider(
        slug="openai",
        title="OpenAI",
        service="openai",
        config=config,
    )

    reopened = ChatStorage(DatabaseSettings(url=temp_store.engine.url.render_as_string(hide_password=False)))
    catalog = reopened.provider_catalog()
    assert catalog["openai"] == ["gpt-5", "gpt-4o-mini"]
