from __future__ import annotations

from pathlib import Path

from app.knowledge.contracts import WriteReceipt
from app.services import vault_sync
from app.write_guard import SOURCE_BACKED_REBUILD_ACTION


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
    # Two calls, not one (#2910): _write_note asserts caller-side, and
    # write_note_from_absolute also asserts at the port seam before any I/O.
    # The caller action is forwarded so named recovery remains identifiable;
    # ordinary writes still hit both guard layers.
    assert calls == ["vault sync note write", "vault sync note write"]


def test_source_backed_rebuild_forwards_action_to_absolute_port(
    monkeypatch, tmp_path: Path
) -> None:
    note_path = tmp_path / "vault" / "Inbox" / "note.md"
    captured: dict[str, object] = {}
    guard_calls: list[str] = []

    def fake_write_note_from_absolute(path, content, *, vault_root, action):  # type: ignore[no-untyped-def]
        captured.update(
            path=Path(path),
            content=content,
            vault_root=Path(vault_root),
            action=action,
        )

    monkeypatch.setattr(vault_sync, "write_note_from_absolute", fake_write_note_from_absolute)
    monkeypatch.setattr(vault_sync.DEFAULT_WRITE_GUARD, "assert_writes_allowed", guard_calls.append)

    vault_sync._write_note(
        note_path,
        {"uuid": "rebuild-uuid"},
        "Body",
        action=SOURCE_BACKED_REBUILD_ACTION,
        vault_root=note_path.parent.parent,
    )

    assert guard_calls == [SOURCE_BACKED_REBUILD_ACTION]
    assert captured["path"] == note_path.resolve()
    assert captured["vault_root"] == note_path.parent.parent.resolve()
    assert captured["action"] == SOURCE_BACKED_REBUILD_ACTION


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


def test_sync_markdown_passes_selected_root_to_replay_producer(
    monkeypatch, tmp_path: Path
) -> None:
    vault_root = tmp_path / "selected-vault"
    note_path = vault_root / "Notes" / "note.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("---\nuuid: selected-root-uuid\n---\n\nBody\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class ReplayReached(RuntimeError):
        pass

    def fake_canonical_note_replay(path, *, vault_root, source_body):  # type: ignore[no-untyped-def]
        captured["path"] = Path(path)
        captured["vault_root"] = Path(vault_root)
        captured["source_text"] = source_body
        raise ReplayReached

    monkeypatch.setattr(vault_sync, "canonical_note_replay", fake_canonical_note_replay)

    try:
        vault_sync.sync_markdown(str(note_path), vault_root=vault_root)
    except ReplayReached:
        pass
    else:  # pragma: no cover - the replay seam must run before database access
        raise AssertionError("sync_markdown did not reach the canonical replay producer")

    assert captured["path"] == note_path.resolve()
    assert captured["vault_root"] == vault_root.resolve()
    assert captured["source_text"] == "Body\n"


def test_sync_markdown_forwards_source_backed_rebuild_action(
    monkeypatch, tmp_path: Path
) -> None:
    vault_root = tmp_path / "selected-vault"
    note_path = vault_root / "Inbox" / "note.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("---\ntitle: Rebuild me\n---\n\nBody\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class ReplayReached(RuntimeError):
        pass

    def fake_write_note(path, frontmatter, body, *, action, vault_root):  # type: ignore[no-untyped-def]
        captured.update(
            path=Path(path),
            frontmatter=frontmatter,
            body=body,
            action=action,
            vault_root=Path(vault_root),
        )

    def fake_canonical_note_replay(path, *, vault_root, source_body):  # type: ignore[no-untyped-def]
        raise ReplayReached

    monkeypatch.setattr(vault_sync, "_write_note", fake_write_note)
    monkeypatch.setattr(vault_sync, "canonical_note_replay", fake_canonical_note_replay)

    try:
        vault_sync.sync_markdown_source_backed_rebuild(
            str(note_path), vault_root=vault_root
        )
    except ReplayReached:
        pass
    else:  # pragma: no cover - the replay seam must run before database access
        raise AssertionError("sync_markdown did not reach the canonical replay producer")

    assert captured["path"] == note_path.resolve()
    assert captured["action"] == SOURCE_BACKED_REBUILD_ACTION
    assert captured["vault_root"] == vault_root.resolve()
