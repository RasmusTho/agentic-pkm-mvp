from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

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


def _resolve_fs_root() -> Path:
    env_root = os.getenv("MCP_VAULT_ROOT") or os.getenv("VAULT_DIR") or os.getenv("VAULT_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return Path("vault").expanduser()


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


def _build_adapter(adapter: KnowledgeAdapter, *, fs_root: Path) -> KnowledgePort:
    if adapter == KnowledgeAdapter.FS_VAULT:
        return FsVaultAdapter(fs_root)
    if adapter == KnowledgeAdapter.OBSIDIAN_CLI:
        return ObsidianCliAdapter()
    raise KnowledgeConfigError(f"Unsupported knowledge adapter: {adapter}")


def resolve_knowledge_port(
    *,
    vault_root: Path | str | None = None,
    settings: KnowledgeSettings | None = None,
) -> KnowledgePort:
    effective = settings or load_knowledge_settings()
    fs_root = Path(vault_root).expanduser().resolve() if vault_root is not None else _resolve_fs_root().resolve()
    if effective.primary_adapter == KnowledgeAdapter.FS_VAULT:
        return FsVaultAdapter(fs_root)

    primary = _build_adapter(effective.primary_adapter, fs_root=fs_root)
    fallback: KnowledgePort | None = None
    if effective.fallback_adapter is not None:
        fallback = _build_adapter(effective.fallback_adapter, fs_root=fs_root)

    status = obsidian_dependency_status()
    if effective.primary_adapter == KnowledgeAdapter.OBSIDIAN_CLI and not status.ok:
        if effective.strict_startup:
            raise KnowledgeDependencyError(
                f"Obsidian CLI adapter is not available: {status.details}"
            )
        if effective.allow_fallback and fallback is not None:
            logger.warning("Obsidian CLI unavailable; using fallback knowledge adapter")
            return fallback

    return HybridKnowledgePort(
        primary=primary,
        fallback=fallback,
        allow_fallback=effective.allow_fallback,
    )


__all__ = ["HybridKnowledgePort", "resolve_knowledge_port"]
