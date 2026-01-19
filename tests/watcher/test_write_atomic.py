from pathlib import Path

from app.watcher import registry


def test_write_markdown_if_changed(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    original = "hello"
    updated = "hello world"
    note.write_text(original, encoding="utf-8")

    wrote = registry._write_markdown_if_changed(note, original, updated)  # type: ignore[attr-defined]
    assert wrote is True
    assert note.read_text(encoding="utf-8") == updated

    wrote_again = registry._write_markdown_if_changed(note, updated, updated)  # type: ignore[attr-defined]
    assert wrote_again is False
    assert note.read_text(encoding="utf-8") == updated
