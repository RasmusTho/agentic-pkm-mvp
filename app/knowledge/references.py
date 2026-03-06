from __future__ import annotations

from urllib.parse import quote

from app.knowledge.contracts import NoteLocator


def build_obsidian_advanced_uri(locator: NoteLocator) -> str:
    return f"obsidian://advanced-uri?vault={quote(locator.vault)}&filepath={quote(locator.path)}"


__all__ = ["build_obsidian_advanced_uri"]
