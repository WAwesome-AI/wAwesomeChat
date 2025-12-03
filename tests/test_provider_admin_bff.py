import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wawesomechat.provider_admin import provider_admin  # noqa: E402


@pytest.fixture
def admin(tmp_path, monkeypatch):
    db_file = tmp_path / "bff_providers.db"
    monkeypatch.setenv("WA_DB_FILE", str(db_file))
    monkeypatch.delenv("WA_DB_URL", raising=False)
    return provider_admin(), db_file


def test_save_provider_persists_grouped_models(admin):
    bff, db_file = admin
    payload = {
        "slug": "aws_bedrock",
        "title": "AWS Bedrock",
        "service": "aws_bedrock",
        "region": "us-east-1",
        "status": "Healthy",
        "pill": "AWS",
        "iconClass": "mdi-alpha-a-circle",
        "models": {
            "anthropic": ["bedrock/us.anthropic.claude-sonnet-4-test"],
            "meta": ["us.meta.llama4-maverick-17b-instruct-v1:0"],
        },
        "type": "aws_bedrock",
        "secrets": {},
        "settings": {"region": "us-east-1"},
    }
    snapshot = bff.save_provider(payload)
    assert db_file.exists()
    catalog = snapshot["catalog"]
    assert "aws_bedrock" in catalog
    assert "bedrock/us.anthropic.claude-sonnet-4-test" in catalog["aws_bedrock"]["anthropic"]

    # New instance should read persisted data
    fresh = provider_admin()
    fresh_snapshot = fresh.get_provider_snapshot()
    stored = fresh_snapshot["catalog"]["aws_bedrock"]["anthropic"]
    assert "bedrock/us.anthropic.claude-sonnet-4-test" in stored


def test_overwrite_models_allows_deletion(admin):
    bff, _ = admin
    slug = "aws_bedrock"
    base_payload = {
        "slug": slug,
        "title": "AWS Bedrock",
        "service": "aws_bedrock",
        "models": {"anthropic": ["m1", "m2"]},
        "type": "aws_bedrock",
        "secrets": {},
    }
    bff.save_provider(base_payload)

    updated = dict(base_payload)
    updated["models"] = {"anthropic": ["m2"]}
    snapshot = bff.save_provider(updated)

    catalog = snapshot["catalog"][slug]["anthropic"]
    assert "m1" not in catalog
    assert catalog == ["m2"]
