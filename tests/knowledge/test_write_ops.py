from __future__ import annotations

from pathlib import Path

from app.knowledge import write_ops
from app.knowledge.contracts import WriteReceipt


def test_default_vault_root_for_path_uses_filesystem_anchor(tmp_path: Path) -> None:
    note = tmp_path / "vault" / "Inbox" / "note.md"
    root = write_ops.default_vault_root_for_path(note)
    assert root == Path(note.anchor)


def test_write_note_from_absolute_resolves_locator_and_port(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, object] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["locator_path"] = locator.path
            captured["locator_vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    def fake_resolve(**kwargs):  # type: ignore[no-untyped-def]
        captured["resolve_kwargs"] = kwargs
        return FakePort()

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", fake_resolve)

    receipt = write_ops.write_note_from_absolute(note, "hello", vault_root=tmp_path / "vault")

    assert receipt.operation == "write_note"
    assert captured["locator_path"] == "Inbox/note.md"
    assert captured["locator_vault"] == "Vault"
    assert captured["content"] == "hello"
    assert captured["resolve_kwargs"] == {"vault_root": (tmp_path / "vault").resolve()}


def test_write_note_relative_uses_make_note_locator(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="write_note", locator=locator, adapter="fake")

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **kwargs: FakePort())

    receipt = write_ops.write_note_relative("Inbox/a.md", "body", vault_root=tmp_path)

    assert receipt.operation == "write_note"
    assert captured["path"] == "Inbox/a.md"
    assert captured["vault"] == "Vault"
    assert captured["content"] == "body"


def test_append_note_relative_uses_port_append(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePort:
        def append_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["vault"] = locator.vault
            captured["content"] = content
            return WriteReceipt(operation="append_note", locator=locator, adapter="fake")

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **kwargs: FakePort())

    receipt = write_ops.append_note_relative("Inbox/log.md", "line\n", vault_root=tmp_path)

    assert receipt.operation == "append_note"
    assert captured["path"] == "Inbox/log.md"
    assert captured["vault"] == "Vault"
    assert captured["content"] == "line\n"


def test_advanced_uri_from_vault_path_inside_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "Inbox" / "a.md"
    uri = write_ops.advanced_uri_from_vault_path(note, vault_root=vault)
    assert "obsidian://advanced-uri" in uri
    assert "filepath=Inbox/a.md" in uri


def test_advanced_uri_from_vault_path_outside_root_falls_back_to_name(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    other = tmp_path / "outside.md"
    uri = write_ops.advanced_uri_from_vault_path(other, vault_root=vault)
    assert "obsidian://advanced-uri" in uri
    assert "filepath=outside.md" in uri
