from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.errors import KnowledgeConfigError
from app.knowledge.adapters import ObsidianCliAdapter
from app.knowledge.service import resolve_knowledge_port
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings


def test_resolve_knowledge_port_does_not_fallback_to_cwd_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("VAULT_ROOT", "VAULT_ROOT_DEV", "VAULT_ROOT_TEST", "MCP_VAULT_ROOT", "VAULT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.FS_VAULT,
        fallback_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        allow_fallback=False,
    )

    with pytest.raises(KnowledgeConfigError, match="Vault root is required"):
        resolve_knowledge_port(settings=settings)


def test_obsidian_primary_does_not_require_fs_fallback_root_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in ("VAULT_ROOT", "VAULT_ROOT_DEV", "VAULT_ROOT_TEST", "MCP_VAULT_ROOT", "VAULT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()
    monkeypatch.setattr(
        "app.knowledge.service.obsidian_dependency_status",
        lambda: type("S", (), {"ok": True, "details": {}})(),
    )
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=True,
        strict_startup=False,
    )

    assert isinstance(resolve_knowledge_port(settings=settings), ObsidianCliAdapter)
