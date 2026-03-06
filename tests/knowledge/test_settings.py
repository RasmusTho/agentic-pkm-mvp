from __future__ import annotations

import pytest

from app.knowledge.errors import KnowledgeConfigError
from app.knowledge.settings import KnowledgeAdapter, load_knowledge_settings


def test_load_knowledge_settings_defaults() -> None:
    settings = load_knowledge_settings({})
    assert settings.primary_adapter == KnowledgeAdapter.OBSIDIAN_CLI
    assert settings.fallback_adapter == KnowledgeAdapter.FS_VAULT
    assert settings.allow_fallback is False
    assert settings.strict_startup is True


def test_load_knowledge_settings_rejects_unknown_adapter() -> None:
    with pytest.raises(KnowledgeConfigError):
        load_knowledge_settings({"KNOWLEDGE_PRIMARY_ADAPTER": "unknown"})


def test_load_knowledge_settings_rejects_same_primary_and_fallback() -> None:
    with pytest.raises(KnowledgeConfigError):
        load_knowledge_settings(
            {
                "KNOWLEDGE_PRIMARY_ADAPTER": "obsidian_cli",
                "KNOWLEDGE_FALLBACK_ADAPTER": "obsidian_cli",
            }
        )


def test_load_knowledge_settings_rejects_strict_with_fallback() -> None:
    with pytest.raises(KnowledgeConfigError):
        load_knowledge_settings(
            {
                "KNOWLEDGE_STRICT_STARTUP": "1",
                "KNOWLEDGE_ALLOW_FALLBACK": "1",
            }
        )


def test_load_knowledge_settings_allows_fallback_when_not_strict() -> None:
    settings = load_knowledge_settings(
        {
            "KNOWLEDGE_STRICT_STARTUP": "0",
            "KNOWLEDGE_ALLOW_FALLBACK": "1",
            "KNOWLEDGE_PRIMARY_ADAPTER": "obsidian_cli",
            "KNOWLEDGE_FALLBACK_ADAPTER": "fs_vault",
        }
    )
    assert settings.strict_startup is False
    assert settings.allow_fallback is True
