from __future__ import annotations

import pytest

from app.knowledge.contracts import NoteLocator


def test_note_locator_accepts_portable_relative_path() -> None:
    locator = NoteLocator(vault="PKM", path="Inbox/note.md")
    assert locator.vault == "PKM"
    assert locator.path == "Inbox/note.md"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute/note.md",
        "C:\\vault\\note.md",
        "Inbox\\note.md",
    ],
)
def test_note_locator_rejects_non_portable_paths(path: str) -> None:
    with pytest.raises(ValueError):
        NoteLocator(vault="PKM", path=path)


def test_note_locator_requires_vault() -> None:
    with pytest.raises(ValueError):
        NoteLocator(vault=" ", path="Inbox/note.md")
