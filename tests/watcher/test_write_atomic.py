from pathlib import Path

from app.knowledge.write_ops import read_note_text_with_version
from app.watcher import registry


def test_write_markdown_if_changed(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    original = "hello"
    updated = "hello world"
    note.write_text(original, encoding="utf-8")

    _, version = read_note_text_with_version(note)
    wrote = registry._write_markdown_if_changed(  # type: ignore[attr-defined]
        note,
        original,
        updated,
        expected_version=version,
        vault_root=tmp_path,
    )
    assert wrote is True
    assert note.read_text(encoding="utf-8") == updated

    _, updated_version = read_note_text_with_version(note)
    wrote_again = registry._write_markdown_if_changed(  # type: ignore[attr-defined]
        note,
        updated,
        updated,
        expected_version=updated_version,
        vault_root=tmp_path,
    )
    assert wrote_again is False
    assert note.read_text(encoding="utf-8") == updated


def test_write_markdown_if_changed_uses_raw_crlf_version(tmp_path: Path) -> None:
    note = tmp_path / "crlf.md"
    raw = b"---\r\nuuid: raw-note\r\n---\r\n\r\nBody\r\n"
    note.write_bytes(raw)
    original, version = registry._read_panel_note_with_retry(note)  # type: ignore[attr-defined]

    wrote = registry._write_markdown_if_changed(  # type: ignore[attr-defined]
        note,
        original,
        original.replace("Body", "Updated"),
        expected_version=version,
        vault_root=tmp_path,
    )

    assert wrote is True
    assert "Updated" in note.read_text(encoding="utf-8")
