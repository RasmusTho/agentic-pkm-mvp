from pathlib import Path

from app.services.note_log import note_log_path


def test_note_log_path_preserves_vault_relative_structure() -> None:
    path = note_log_path("1234-uuid", "Workspace/Area1/note.md")
    assert path == Path("System/Metadata/VaultMirror/Workspace/Area1/1234-uuid.md")


def test_note_log_path_strips_leading_slash() -> None:
    path = note_log_path("abcd", "/Projects/X.md")
    assert path == Path("System/Metadata/VaultMirror/Projects/abcd.md")
