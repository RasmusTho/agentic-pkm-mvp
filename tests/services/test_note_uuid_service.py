from __future__ import annotations

from pathlib import Path

from app.services import note_uuid


def test_ensure_note_uuid_keeps_existing_uuid_without_write(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("---\nuuid: existing-uuid\n---\n\nBody\n", encoding="utf-8")
    calls: list[str] = []

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            calls.append(locator.path)
            return None

    monkeypatch.setattr(note_uuid, "resolve_knowledge_port", lambda **kwargs: FakePort())
    result = note_uuid.ensure_note_uuid(note)
    assert result == "existing-uuid"
    assert calls == []


def test_ensure_note_uuid_writes_via_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body\n", encoding="utf-8")
    captured: dict[str, str] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["content"] = content
            return None

    monkeypatch.setattr(note_uuid, "resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr(note_uuid.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    result = note_uuid.ensure_note_uuid(note, preferred_uuid="fixed-uuid")
    assert result == "fixed-uuid"
    assert captured["path"] == "note.md"
    assert "uuid: fixed-uuid" in captured["content"]
