from __future__ import annotations

from pathlib import Path

from app.ports.filesystem_vault_adapter import FilesystemVaultAdapter


def test_adapter_exposes_vault_port_lifecycle_methods(tmp_path: Path) -> None:
    adapter = FilesystemVaultAdapter(vault_root=tmp_path)
    for method in (
        "read_note",
        "ensure_uuid",
        "write_frontmatter",
        "rename_note",
        "delete_note",
        "upsert_note_object",
        "append_inbox_item",
    ):
        assert hasattr(adapter, method)


def test_ensure_uuid_writes_frontmatter_when_missing(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body", encoding="utf-8")
    adapter = FilesystemVaultAdapter(vault_root=tmp_path, backend_writes_enabled=False)
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.active_edit", lambda _: False)
    writes: list[str] = []
    monkeypatch.setattr(
        "app.ports.filesystem_vault_adapter.write_note_from_absolute",
        lambda path, content, vault_root=None: writes.append(content),
    )
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.append_change", lambda *a, **k: None)

    read = adapter.read_note(note)
    result = adapter.ensure_uuid(read, expected_mtime_ns=read.mtime_ns)

    assert result.wrote
    assert result.uuid_value
    assert writes and "uuid:" in writes[0]


def test_ensure_uuid_defers_on_mtime_mismatch(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body", encoding="utf-8")
    adapter = FilesystemVaultAdapter(vault_root=tmp_path, backend_writes_enabled=False)
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.active_edit", lambda _: False)
    messages: list[str] = []
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.append_change", lambda msg, **kwargs: messages.append(msg))
    monkeypatch.setattr(
        "app.ports.filesystem_vault_adapter.write_note_from_absolute",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("write should be skipped")),
    )

    read = adapter.read_note(note)
    note.write_text("User changed this", encoding="utf-8")
    result = adapter.ensure_uuid(read, expected_mtime_ns=read.mtime_ns)

    assert result.deferred
    assert result.reason == "mtime_mismatch"
    assert any("concurrent edit" in msg for msg in messages)


def test_ensure_uuid_defers_on_active_edit(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body", encoding="utf-8")
    adapter = FilesystemVaultAdapter(vault_root=tmp_path, backend_writes_enabled=False)
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.active_edit", lambda _: True)
    messages: list[str] = []
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.append_change", lambda msg, **kwargs: messages.append(msg))

    read = adapter.read_note(note)
    result = adapter.ensure_uuid(read, expected_mtime_ns=read.mtime_ns)

    assert result.deferred
    assert result.reason == "active_edit"
    assert any("Deferred UUID injection" in msg for msg in messages)


def test_backend_calls_are_gated_when_backend_disabled(monkeypatch, tmp_path: Path) -> None:
    adapter = FilesystemVaultAdapter(vault_root=tmp_path, backend_writes_enabled=False)
    monkeypatch.setattr(
        "app.ports.filesystem_vault_adapter.update_path",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rename backend call should be skipped")),
    )
    monkeypatch.setattr(
        "app.ports.filesystem_vault_adapter.delete_note",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("delete backend call should be skipped")),
    )
    monkeypatch.setattr(
        "app.ports.filesystem_vault_adapter.upsert_object_from_note",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("upsert backend call should be skipped")),
    )

    adapter.rename_note("u1", tmp_path / "new.md")
    adapter.delete_note(tmp_path / "gone.md", uuid_value="u1")
    adapter.upsert_note_object(tmp_path / "n.md", {"uuid": "u1"}, "Body", True, True)
