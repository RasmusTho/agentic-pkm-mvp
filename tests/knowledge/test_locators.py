from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.locators import make_note_locator, make_note_locator_from_absolute, normalize_note_path


def test_normalize_note_path_converts_backslashes() -> None:
    assert normalize_note_path(r"Inbox\A.md") == "Inbox/A.md"


def test_make_note_locator_uses_default_vault_and_normalized_path() -> None:
    locator = make_note_locator(r"Inbox\A.md")
    assert locator.vault == "Vault"
    assert locator.path == "Inbox/A.md"


def test_make_note_locator_supports_explicit_vault() -> None:
    locator = make_note_locator("Inbox/A.md", vault="Mimer")
    assert locator.vault == "Mimer"
    assert locator.path == "Inbox/A.md"


def test_make_note_locator_from_absolute_computes_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    note = root / "Inbox" / "A.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("x", encoding="utf-8")
    locator = make_note_locator_from_absolute(note, vault_root=root, vault="Mimer")
    assert locator.vault == "Mimer"
    assert locator.path == "Inbox/A.md"


def test_make_note_locator_from_absolute_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    other = tmp_path / "outside.md"
    with pytest.raises(ValueError):
        make_note_locator_from_absolute(other, vault_root=root)
