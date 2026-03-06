from __future__ import annotations

from app.knowledge.contracts import NoteLocator
from app.knowledge.references import build_obsidian_advanced_uri


def test_build_obsidian_advanced_uri_encodes_vault_and_path() -> None:
    uri = build_obsidian_advanced_uri(NoteLocator(vault="PKM Vault", path="Inbox/Hej världen.md"))
    assert uri.startswith("obsidian://advanced-uri?vault=PKM%20Vault&filepath=Inbox/Hej%20v%C3%A4rlden.md")
