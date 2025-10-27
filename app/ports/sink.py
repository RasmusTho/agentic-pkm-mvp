from __future__ import annotations

from typing import Any, Protocol


class Sink(Protocol):
    def update_path(self, uuid_value: str, new_path: str) -> None: ...

    def upsert_object_from_note(self, path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool) -> None: ...


class DummySink:
    def __init__(self) -> None:
        self.updates: list[tuple[str, str]] = []
        self.upserts: list[tuple[str, dict[str, Any], str, bool, bool]] = []

    def update_path(self, uuid_value: str, new_path: str) -> None:
        self.updates.append((uuid_value, new_path))

    def upsert_object_from_note(self, path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool) -> None:
        self.upserts.append((path, frontmatter, body, fm_changed, body_changed))


__all__ = ["DummySink", "Sink"]
