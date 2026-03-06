from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


def _is_probably_absolute(path: str) -> bool:
    return path.startswith("/") or (len(path) > 1 and path[1] == ":" and path[0].isalpha())


@dataclass(frozen=True)
class NoteLocator:
    """Portable note identity in the knowledge layer."""

    vault: str
    path: str

    def __post_init__(self) -> None:
        vault = self.vault.strip()
        path = self.path.strip()
        if not vault:
            raise ValueError("vault is required")
        if not path:
            raise ValueError("path is required")
        if _is_probably_absolute(path):
            raise ValueError("path must be vault-relative")
        if "\\" in path:
            raise ValueError("path must use portable separators ('/')")
        object.__setattr__(self, "vault", vault)
        object.__setattr__(self, "path", path)


@dataclass(frozen=True)
class SearchHit:
    locator: NoteLocator
    score: float
    excerpt: str


@dataclass(frozen=True)
class WriteReceipt:
    operation: str
    locator: NoteLocator
    adapter: str
    trace_id: str | None = None
    fallback_used: bool = False


class KnowledgePort(Protocol):
    """Domain-facing abstraction for vault/knowledge operations."""

    def read_note(self, locator: NoteLocator) -> str: ...

    def write_note(self, locator: NoteLocator, content: str) -> WriteReceipt: ...

    def append_note(self, locator: NoteLocator, content: str) -> WriteReceipt: ...

    def prepend_note(self, locator: NoteLocator, content: str) -> WriteReceipt: ...

    def search_notes(self, vault: str, query: str, *, limit: int = 20) -> list[SearchHit]: ...

    def open_note(self, locator: NoteLocator) -> None: ...


__all__ = ["KnowledgePort", "NoteLocator", "SearchHit", "WriteReceipt"]
