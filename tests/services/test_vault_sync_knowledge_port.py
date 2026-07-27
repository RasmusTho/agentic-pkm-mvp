from __future__ import annotations

from pathlib import Path

from app.knowledge.contracts import WriteReceipt
from app.services import vault_sync


def test_write_note_routes_through_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, str] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "Mimer")
    monkeypatch.setattr("app.knowledge.write_ops.resolve_knowledge_port", lambda **kwargs: FakePort())
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
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    monkeypatch.setattr("app.knowledge.write_ops.resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", calls.append)

    vault_sync._write_note(note_path, {"uuid": "u2"}, "Body")
    # Two calls, not one (#2910): _write_note asserts caller-side ("vault sync
    # note write", defense-in-depth per #2808's pattern), and
    # write_note_from_absolute now ALSO asserts at the port seam itself with
    # its own default action ("knowledge.write_note") before any I/O -- both
    # assertions hit the same DEFAULT_WRITE_GUARD singleton this test patched.
    assert calls == ["vault sync note write", "knowledge.write_note"]


def test_write_note_falls_back_to_default_vault_when_env_blank(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, str] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["vault"] = locator.vault
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "   ")
    monkeypatch.setattr("app.knowledge.write_ops.resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    vault_sync._write_note(note_path, {"uuid": "u3"}, "Body")
    assert captured["vault"] == "Vault"


def test_write_note_uses_absolute_locator_factory(monkeypatch, tmp_path: Path) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, Path] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    def fake_locator(path, *, vault_root, vault=None):  # type: ignore[no-untyped-def]
        captured["path"] = Path(path)
        captured["vault_root"] = Path(vault_root)
        return type("L", (), {"path": "Inbox/note.md", "vault": "Vault"})()

    monkeypatch.setattr("app.knowledge.write_ops.resolve_knowledge_port", lambda **kwargs: FakePort())
    monkeypatch.setattr("app.knowledge.write_ops.make_note_locator_from_absolute", fake_locator)
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    vault_sync._write_note(note_path, {"uuid": "u4"}, "Body")
    assert captured["path"] == note_path.resolve()
    assert captured["vault_root"] == Path(note_path.anchor)
