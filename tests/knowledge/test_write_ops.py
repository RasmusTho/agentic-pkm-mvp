from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.knowledge import write_ops
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings
from app.write_guard import WriteGuard, WritesBlockedError


def test_default_vault_root_for_path_uses_filesystem_anchor(tmp_path: Path) -> None:
    note = tmp_path / "vault" / "Inbox" / "note.md"
    root = write_ops.default_vault_root_for_path(note)
    assert root == Path(note.anchor)


def test_read_note_text_with_version_hashes_exact_raw_bytes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    raw = b"---\r\nuuid: crlf-note\r\n---\r\n\r\nBody\r\n"
    note.write_bytes(raw)

    text, version = write_ops.read_note_text_with_version(note)

    assert text.encode("utf-8") == raw
    assert version == hashlib.sha256(raw).hexdigest()


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
    assert captured["resolve_kwargs"] == {
        "vault_root": (tmp_path / "vault").resolve(),
        "settings": KnowledgeSettings(
            primary_adapter=KnowledgeAdapter.FS_VAULT,
            fallback_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
            allow_fallback=False,
            strict_startup=False,
        ),
    }


def test_write_note_from_absolute_rejects_outside_vault_root_before_writing(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside" / "note.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("old", encoding="utf-8")
    vault.mkdir()
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )

    try:
        write_ops.write_note_from_absolute(outside, "new", vault_root=vault)
    except ValueError:
        pass
    else:
        raise AssertionError("outside path was accepted")

    assert outside.read_text(encoding="utf-8") == "old"


def test_write_note_from_absolute_rejects_symlink_escape(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    escaped = outside / "note.md"
    escaped.write_text("old", encoding="utf-8")
    link = vault / "linked.md"
    link.symlink_to(escaped)
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )

    try:
        write_ops.write_note_from_absolute(link, "new", vault_root=vault)
    except ValueError:
        pass
    else:
        raise AssertionError("symlink escape was accepted")

    assert escaped.read_text(encoding="utf-8") == "old"


def test_absolute_helper_rejects_expected_version_through_source_symlink_alias(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Sources" / "panel-source.md"
    target.parent.mkdir(parents=True)
    target.write_text("observed source", encoding="utf-8")
    alias = vault / "Notes" / "source-alias.md"
    alias.parent.mkdir()
    alias.symlink_to(Path("..") / "Sources" / target.name)
    _, expected_version = write_ops.read_note_text_with_version(alias)
    target.write_text("concurrent human source", encoding="utf-8")

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write requires a rewritten note class",
    ):
        write_ops.write_note_from_absolute(
            alias,
            "stale watcher proposal",
            vault_root=vault,
            expected_version=expected_version,
        )

    assert target.read_text(encoding="utf-8") == "concurrent human source"
    assert alias.read_text(encoding="utf-8") == "concurrent human source"


def test_relative_helper_rejects_expected_version_through_source_symlink_alias(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    target = vault / "Sources" / "panel-source.md"
    target.parent.mkdir(parents=True)
    target.write_text("observed source", encoding="utf-8")
    alias = vault / "Notes" / "source-alias.md"
    alias.parent.mkdir()
    alias.symlink_to(Path("..") / "Sources" / target.name)
    _, expected_version = write_ops.read_note_text_with_version(alias)
    target.write_text("concurrent human source", encoding="utf-8")

    with pytest.raises(
        KnowledgeWriteConflict,
        match="expected-version write requires a rewritten note class",
    ):
        write_ops.write_note_relative(
            "Notes/source-alias.md",
            "stale watcher proposal",
            vault_root=vault,
            expected_version=expected_version,
        )

    assert target.read_text(encoding="utf-8") == "concurrent human source"
    assert alias.read_text(encoding="utf-8") == "concurrent human source"


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


@pytest.mark.parametrize("relative", [False, True])
def test_write_helpers_raise_with_staged_receipt_by_default(
    relative: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, WriteReceipt] = {}

    class FakePort:
        def write_note(self, locator, content, **kwargs):  # type: ignore[no-untyped-def]
            receipt = WriteReceipt(
                operation="write_note",
                locator=locator,
                adapter="fake",
                outcome="conflict_staged",
                conflict_artifact="Inbox/note.concurrent-save-test.md",
            )
            captured["receipt"] = receipt
            return receipt

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **_kwargs: FakePort())

    with pytest.raises(KnowledgeWriteConflict, match="conflict staged") as exc_info:
        if relative:
            write_ops.write_note_relative(
                "Inbox/note.md",
                "proposal",
                vault_root=tmp_path,
                expected_version="stale",
            )
        else:
            note = tmp_path / "Inbox" / "note.md"
            write_ops.write_note_from_absolute(
                note,
                "proposal",
                vault_root=tmp_path,
                expected_version="stale",
            )

    assert exc_info.value.receipt is captured["receipt"]


@pytest.mark.parametrize("relative", [False, True])
def test_write_helpers_return_staged_receipt_only_for_explicitly_aware_caller(
    relative: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakePort:
        def write_note(self, locator, content, **kwargs):  # type: ignore[no-untyped-def]
            return WriteReceipt(
                operation="write_note",
                locator=locator,
                adapter="fake",
                outcome="conflict_staged",
                conflict_artifact="Inbox/note.concurrent-save-test.md",
            )

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **_kwargs: FakePort())

    if relative:
        receipt = write_ops.write_note_relative(
            "Inbox/note.md",
            "proposal",
            vault_root=tmp_path,
            expected_version="stale",
            accept_staged_conflict=True,
        )
    else:
        receipt = write_ops.write_note_from_absolute(
            tmp_path / "Inbox" / "note.md",
            "proposal",
            vault_root=tmp_path,
            expected_version="stale",
            accept_staged_conflict=True,
        )

    assert receipt.outcome == "conflict_staged"
    assert receipt.conflict_artifact == "Inbox/note.concurrent-save-test.md"


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


def test_append_note_relative_rejects_unhealthy_write_guard(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        write_ops,
        "resolve_knowledge_port",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("port should not resolve")),
    )
    guard = WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})

    with pytest.raises(WritesBlockedError):
        write_ops.append_note_relative(
            "Inbox/log.md",
            "line\n",
            vault_root=tmp_path,
            write_guard=guard,
        )


def test_append_note_relative_allows_healthy_write_guard(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakePort:
        def append_note(self, locator, content):  # type: ignore[no-untyped-def]
            captured["path"] = locator.path
            captured["content"] = content
            return WriteReceipt(operation="append_note", locator=locator, adapter="fake")

    monkeypatch.setattr(write_ops, "resolve_knowledge_port", lambda **_kwargs: FakePort())
    guard = WriteGuard(lambda: {"state": "healthy", "reason": None})

    receipt = write_ops.append_note_relative(
        "Inbox/log.md",
        "line\n",
        vault_root=tmp_path,
        write_guard=guard,
    )

    assert receipt.operation == "append_note"
    assert captured == {"path": "Inbox/log.md", "content": "line\n"}


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
