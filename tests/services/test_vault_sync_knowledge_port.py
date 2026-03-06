from __future__ import annotations

from pathlib import Path

from app.services import vault_sync


def test_write_note_routes_through_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, str] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["vault"] = locator.vault
            captured["content"] = content
            return None

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "Mimer")
    monkeypatch.setattr(vault_sync, "resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    vault_sync._write_note(note_path, {"uuid": "u1", "title": "T"}, "Body")

    assert captured["vault"] == "Mimer"
    expected_rel = note_path.resolve().relative_to(Path(note_path.anchor)).as_posix()
    assert captured["path"] == expected_rel
    assert "uuid: u1" in captured["content"]
    assert captured["content"].startswith("---\n")


def test_write_note_checks_write_guard(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    calls: list[str] = []

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(vault_sync, "resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", calls.append)

    vault_sync._write_note(note_path, {"uuid": "u2"}, "Body")
    assert calls == ["vault sync note write"]


def test_write_note_falls_back_to_default_vault_when_env_blank(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, str] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["vault"] = locator.vault
            return None

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "   ")
    monkeypatch.setattr(vault_sync, "resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    vault_sync._write_note(note_path, {"uuid": "u3"}, "Body")
    assert captured["vault"] == "Vault"
