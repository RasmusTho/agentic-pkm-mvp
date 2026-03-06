from __future__ import annotations

import os
from pathlib import Path

from app.knowledge.adapters import FsVaultAdapter, ObsidianCliAdapter
from app.knowledge.contracts import KnowledgePort
from app.knowledge.errors import KnowledgeConfigError, KnowledgeDependencyError
from app.knowledge.health import obsidian_dependency_status
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings, load_knowledge_settings


def _resolve_fs_root() -> Path:
    env_root = os.getenv("MCP_VAULT_ROOT") or os.getenv("VAULT_DIR") or os.getenv("VAULT_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return Path("vault").expanduser()


def resolve_knowledge_port(
    *,
    vault_root: Path | str | None = None,
    settings: KnowledgeSettings | None = None,
) -> KnowledgePort:
    if vault_root is not None:
        return FsVaultAdapter(vault_root)

    effective = settings or load_knowledge_settings()
    if effective.primary_adapter == KnowledgeAdapter.FS_VAULT:
        return FsVaultAdapter(_resolve_fs_root())

    dep = obsidian_dependency_status()
    if dep.ok:
        return ObsidianCliAdapter()

    if effective.strict_startup:
        raise KnowledgeDependencyError(f"Obsidian dependency check failed: {dep.details}")
    if not effective.allow_fallback:
        raise KnowledgeDependencyError("Obsidian dependency unavailable and fallback is disabled")
    if effective.fallback_adapter != KnowledgeAdapter.FS_VAULT:
        raise KnowledgeConfigError("Only fs_vault fallback is supported in non-strict mode")
    return FsVaultAdapter(_resolve_fs_root())


__all__ = ["resolve_knowledge_port"]
