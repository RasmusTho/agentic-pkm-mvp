from __future__ import annotations

import pytest

from app.knowledge.adapters import FsVaultAdapter
from app.knowledge.errors import KnowledgeDependencyError
from app.knowledge.service import resolve_knowledge_port
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings


def test_resolve_knowledge_port_uses_fs_when_vault_root_given(tmp_path) -> None:
    port = resolve_knowledge_port(vault_root=tmp_path)
    assert isinstance(port, FsVaultAdapter)


def test_resolve_knowledge_port_strict_raises_on_missing_obsidian(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": False, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=False,
        strict_startup=True,
    )
    with pytest.raises(KnowledgeDependencyError):
        resolve_knowledge_port(settings=settings)


def test_resolve_knowledge_port_can_fallback_when_non_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.knowledge.service.obsidian_dependency_status", lambda: type("S", (), {"ok": False, "details": {}})())
    settings = KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        fallback_adapter=KnowledgeAdapter.FS_VAULT,
        allow_fallback=True,
        strict_startup=False,
    )
    port = resolve_knowledge_port(settings=settings)
    assert isinstance(port, FsVaultAdapter)
