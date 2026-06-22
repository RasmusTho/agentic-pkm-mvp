from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable, TypeVar, cast

from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.knowledge.adapters import FsVaultAdapter, ObsidianCliAdapter
from app.knowledge.contracts import KnowledgePort, NoteLocator, SearchHit, WriteReceipt
from app.knowledge.errors import (
    KnowledgeConfigError,
    KnowledgeDependencyError,
    KnowledgeTransportError,
)
from app.knowledge.health import obsidian_dependency_status
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings, load_knowledge_settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _resolve_fs_root(vault_root: Path | str | None = None) -> Path | None:
    if vault_root is not None:
        return Path(vault_root).expanduser().resolve()
    for env_var in ("MCP_VAULT_ROOT", "VAULT_DIR"):
        env_root = os.getenv(env_var)
        if not env_root or not env_root.strip():
            continue
        path = Path(env_root).expanduser()
        if not path.exists():
            exc = VaultRootMisconfiguredError(env_var, path)
            raise KnowledgeConfigError(str(exc)) from exc
        return path.resolve()
    try:
        return resolve_optional_vault_root()
    except VaultRootMisconfiguredError as exc:
        raise KnowledgeConfigError(str(exc)) from exc


class HybridKnowledgePort:
    def __init__(
        self,
        *,
        primary: KnowledgePort,
        fallback: KnowledgePort | None,
        allow_fallback: bool,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.allow_fallback = allow_fallback

    def _execute_with_fallback(
        self,
        operation: str,
        runner: Callable[[KnowledgePort], _T],
        subject: str,
    ) -> _T:
        try:
            return runner(self.primary)
        except (KnowledgeDependencyError, KnowledgeTransportError) as exc:
            if not self.allow_fallback or self.fallback is None:
                raise
            logger.warning(
                "Knowledge fallback used for %s on %s after %s: %s",
                operation,
                subject,
                type(exc).__name__,
                exc,
            )
            result = runner(self.fallback)
            if isinstance(result, WriteReceipt):
                return cast(_T, replace(result, fallback_used=True))
            return result

    def read_note(self, locator: NoteLocator) -> str:
        return self._execute_with_fallback(
            "read_note",
            lambda port: port.read_note(locator),
            f"{locator.vault}:{locator.path}",
        )

    def write_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        return self._execute_with_fallback(
            "write_note",
            lambda port: port.write_note(locator, content),
            f"{locator.vault}:{locator.path}",
        )

    def append_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        return self._execute_with_fallback(
            "append_note",
            lambda port: port.append_note(locator, content),
            f"{locator.vault}:{locator.path}",
        )

    def prepend_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        return self._execute_with_fallback(
            "prepend_note",
            lambda port: port.prepend_note(locator, content),
            f"{locator.vault}:{locator.path}",
        )

    def search_notes(self, vault: str, query: str, *, limit: int = 20) -> list[SearchHit]:
        return self._execute_with_fallback(
            "search_notes",
            lambda port: port.search_notes(vault, query, limit=limit),
            f"{vault}:{query}",
        )

    def open_note(self, locator: NoteLocator) -> None:
        self._execute_with_fallback(
            "open_note",
            lambda port: port.open_note(locator),
            f"{locator.vault}:{locator.path}",
        )


def _build_adapter(adapter: KnowledgeAdapter, *, fs_root: Path | None) -> KnowledgePort:
    if adapter == KnowledgeAdapter.FS_VAULT:
        if fs_root is None:
            raise KnowledgeConfigError(
                "Vault root is required for fs_vault knowledge adapter; pass vault_root or configure VAULT_ROOT."
            )
        return FsVaultAdapter(fs_root)
    if adapter == KnowledgeAdapter.OBSIDIAN_CLI:
        return ObsidianCliAdapter()
    raise KnowledgeConfigError(f"Unsupported knowledge adapter: {adapter}")


def _build_fs_fallback(vault_root: Path | str | None, adapter: KnowledgeAdapter | None) -> KnowledgePort | None:
    if adapter is None:
        return None
    fs_root = _resolve_fs_root(vault_root) if adapter == KnowledgeAdapter.FS_VAULT else None
    return _build_adapter(adapter, fs_root=fs_root)


def resolve_knowledge_port(
    *,
    vault_root: Path | str | None = None,
    settings: KnowledgeSettings | None = None,
) -> KnowledgePort:
    effective = settings or load_knowledge_settings()
    if effective.primary_adapter == KnowledgeAdapter.FS_VAULT:
        return _build_adapter(effective.primary_adapter, fs_root=_resolve_fs_root(vault_root))

    primary = _build_adapter(effective.primary_adapter, fs_root=None)

    status = obsidian_dependency_status()
    if effective.primary_adapter == KnowledgeAdapter.OBSIDIAN_CLI and not status.ok:
        if effective.strict_startup:
            raise KnowledgeDependencyError(
                f"Obsidian CLI adapter is not available: {status.details}"
            )
        if effective.allow_fallback and effective.fallback_adapter is not None:
            fallback = _build_fs_fallback(vault_root, effective.fallback_adapter)
            if fallback is None:
                raise KnowledgeConfigError("Fallback knowledge adapter is not configured")
            logger.warning("Obsidian CLI unavailable; using fallback knowledge adapter")
            return fallback

    if not effective.allow_fallback or effective.fallback_adapter is None:
        return primary

    try:
        fallback = _build_fs_fallback(vault_root, effective.fallback_adapter)
    except KnowledgeConfigError:
        return primary
    if fallback is None:
        return primary
    return HybridKnowledgePort(
        primary=primary,
        fallback=fallback,
        allow_fallback=effective.allow_fallback,
    )


__all__ = ["HybridKnowledgePort", "resolve_knowledge_port"]
