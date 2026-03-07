from __future__ import annotations

from pathlib import Path

from app.services.inbox import append_change


def test_append_change_writes_line_via_default_fs_port(tmp_path: Path) -> None:
    note_rel = "Inbox/_system_changes.md"
    append_change("hello", note_rel_path=note_rel, vault_root=tmp_path)
    target = tmp_path / note_rel
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "hello" in content


def test_append_change_uses_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    class FakePort:
        def append_note(self, locator, content):  # type: ignore[no-untyped-def]
            calls.append((locator.path, content))
            return None

    monkeypatch.setattr("app.services.inbox.resolve_knowledge_port", lambda **kwargs: FakePort())
    append_change("world", note_rel_path="Inbox/_system_changes.md", vault_root=tmp_path)
    assert calls
    assert calls[0][0] == "Inbox/_system_changes.md"
    assert "world" in calls[0][1]


def test_append_change_falls_back_to_default_vault_when_env_blank(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    class FakePort:
        def append_note(self, locator, content):  # type: ignore[no-untyped-def]
            calls.append(locator.vault)
            return None

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "   ")
    monkeypatch.setattr("app.services.inbox.resolve_knowledge_port", lambda **kwargs: FakePort())
    append_change("world", note_rel_path="Inbox/_system_changes.md", vault_root=tmp_path)
    assert calls == ["Vault"]
