from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from app.knowledge.errors import KnowledgeConfigError

_TRUE_VALUES = {"1", "true", "yes", "on"}


class KnowledgeAdapter(str, Enum):
    OBSIDIAN_CLI = "obsidian_cli"
    FS_VAULT = "fs_vault"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def _parse_adapter(raw: str | None, *, field_name: str, default: KnowledgeAdapter) -> KnowledgeAdapter:
    value = (raw or "").strip()
    if not value:
        return default
    try:
        return KnowledgeAdapter(value)
    except ValueError as exc:
        allowed = ", ".join(adapter.value for adapter in KnowledgeAdapter)
        raise KnowledgeConfigError(f"{field_name} must be one of: {allowed}") from exc


@dataclass(frozen=True)
class KnowledgeSettings:
    primary_adapter: KnowledgeAdapter = KnowledgeAdapter.OBSIDIAN_CLI
    fallback_adapter: KnowledgeAdapter = KnowledgeAdapter.FS_VAULT
    allow_fallback: bool = False
    strict_startup: bool = True

    def validate(self) -> None:
        if self.primary_adapter == self.fallback_adapter:
            raise KnowledgeConfigError("primary_adapter and fallback_adapter must differ")
        if self.strict_startup and self.allow_fallback:
            raise KnowledgeConfigError("strict_startup=1 cannot be combined with allow_fallback=1")


def load_knowledge_settings(env: Mapping[str, str] | None = None) -> KnowledgeSettings:
    source = env if env is not None else os.environ
    settings = KnowledgeSettings(
        primary_adapter=_parse_adapter(
            source.get("KNOWLEDGE_PRIMARY_ADAPTER"),
            field_name="KNOWLEDGE_PRIMARY_ADAPTER",
            default=KnowledgeAdapter.OBSIDIAN_CLI,
        ),
        fallback_adapter=_parse_adapter(
            source.get("KNOWLEDGE_FALLBACK_ADAPTER"),
            field_name="KNOWLEDGE_FALLBACK_ADAPTER",
            default=KnowledgeAdapter.FS_VAULT,
        ),
        allow_fallback=_as_bool(source.get("KNOWLEDGE_ALLOW_FALLBACK"), False),
        strict_startup=_as_bool(source.get("KNOWLEDGE_STRICT_STARTUP"), True),
    )
    settings.validate()
    return settings


__all__ = ["KnowledgeAdapter", "KnowledgeSettings", "load_knowledge_settings"]
