import os
from importlib import reload
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_watcher(monkeypatch, vault_dir: Path):
    monkeypatch.setenv("VAULT_DIR", str(vault_dir))
    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "TestVault")
    import scripts.fs_watcher as watcher  # type: ignore

    reload(watcher)
    watcher.STATE.clear()
    watcher.UUID_INDEX.clear()
    return watcher


def test_scan_injects_uuid_and_upserts(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("Plain body", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)

    calls = SimpleNamespace(upsert=None, updates=0, messages=[])

    def fake_upsert(path, fm, body, changed_fm, changed_body):  # noqa: D401
        calls.upsert = (path, fm, body, changed_fm, changed_body)

    monkeypatch.setattr(watcher, "upsert_object_from_note", fake_upsert)
    monkeypatch.setattr(watcher, "update_path", lambda *a, **k: None)
    monkeypatch.setattr(watcher, "active_edit", lambda p: False)

    def fake_append(msg, **kw):
        calls.messages.append((msg, kw))

    monkeypatch.setattr(watcher, "append_change", fake_append)

    watcher.scan_once()

    assert calls.upsert is not None
    _, fm, _, _, _ = calls.upsert
    assert "uuid" in fm
    assert any("obsidian://advanced-uri" in (kw.get("uri") or "") for _, kw in calls.messages)
    content = note.read_text(encoding="utf-8")
    assert "uuid:" in content


def test_rename_only_updates_path(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "alpha.md"
    note.write_text("---\nuuid: 1234\n---\n\nBody", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)

    upserts = []
    monkeypatch.setattr(watcher, "upsert_object_from_note", lambda *a, **k: upserts.append(a))
    updated = {}
    monkeypatch.setattr(watcher, "update_path", lambda uuid, new: updated.setdefault(uuid, new))
    monkeypatch.setattr(watcher, "active_edit", lambda p: False)
    monkeypatch.setattr(watcher, "append_change", lambda *a, **k: None)

    watcher.scan_once()
    upserts.clear()

    renamed = vault / "beta.md"
    note.rename(renamed)

    watcher.scan_once()

    assert updated == {"1234": str(renamed)}
    assert not upserts


def test_active_edit_skips(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("---\nuuid: 5678\n---\n\nBody", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)

    monkeypatch.setattr(watcher, "active_edit", lambda p: True)
    upserts = []
    monkeypatch.setattr(watcher, "upsert_object_from_note", lambda *a, **k: upserts.append(a))

    messages = []
    monkeypatch.setattr(watcher, "append_change", lambda *a, **k: messages.append((a, k)))

    watcher.scan_once()

    assert not upserts
    assert messages
    assert "Deferred" in messages[0][0][0]
