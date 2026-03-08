from __future__ import annotations

from pathlib import Path

from app.services import note_uuid


def test_ensure_note_uuid_keeps_existing_uuid_without_write(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("---\nuuid: existing-uuid\n---\n\nBody\n", encoding="utf-8")
    calls: list[str] = []

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        calls.append(str(path))
        return None

    monkeypatch.setattr(note_uuid, "write_note_from_absolute", _fake_write)
    result = note_uuid.ensure_note_uuid(note)
    assert result == "existing-uuid"
    assert calls == []


def test_ensure_note_uuid_writes_via_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body\n", encoding="utf-8")
    captured: dict[str, str] = {}

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        captured["path"] = Path(path).resolve().relative_to(Path(path).anchor).as_posix()
        captured["content"] = content
        return None

    monkeypatch.setattr(note_uuid, "write_note_from_absolute", _fake_write)
    monkeypatch.setattr(note_uuid.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    result = note_uuid.ensure_note_uuid(note, preferred_uuid="fixed-uuid")
    assert result == "fixed-uuid"
    expected_path = note.resolve().relative_to(Path(note.anchor)).as_posix()
    assert captured["path"] == expected_path
    assert "uuid: fixed-uuid" in captured["content"]
