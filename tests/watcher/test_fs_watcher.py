from importlib import reload
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ports.sink import DummySink


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

    monkeypatch.setattr(watcher, "active_edit", lambda p: False)

    def fake_append(msg, **kw):
        calls.messages.append((msg, kw))

    monkeypatch.setattr(watcher, "append_change", fake_append)

    sink = DummySink()
    watcher.scan_once(sink)

    assert sink.upserts
    _, fm, _, _, _ = sink.upserts[-1]
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

    monkeypatch.setattr(watcher, "active_edit", lambda p: False)
    monkeypatch.setattr(watcher, "append_change", lambda *a, **k: None)

    sink = DummySink()
    watcher.scan_once(sink)
    sink.upserts.clear()
    sink.updates.clear()

    renamed = vault / "beta.md"
    note.rename(renamed)

    watcher.scan_once(sink)

    assert sink.updates == [("1234", str(renamed))]
    assert not sink.upserts


def test_active_edit_skips(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("---\nuuid: 5678\n---\n\nBody", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)

    monkeypatch.setattr(watcher, "active_edit", lambda p: True)

    messages = []
    monkeypatch.setattr(watcher, "append_change", lambda *a, **k: messages.append((a, k)))

    sink = DummySink()
    watcher.scan_once(sink)

    assert not sink.upserts
    assert messages
    assert "Deferred" in messages[0][0][0]


def test_uri_falls_back_to_default_vault_when_env_blank(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("---\nuuid: 9012\n---\n\nBody", encoding="utf-8")

    monkeypatch.setenv("VAULT_DIR", str(vault))
    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "   ")
    import scripts.fs_watcher as watcher  # type: ignore

    reload(watcher)
    uri = watcher._make_uri(note)
    assert "obsidian://advanced-uri" in uri
    assert "vault=Vault" in uri


def test_uuid_injection_writes_via_knowledge_port(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("Body", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    monkeypatch.setattr(watcher, "active_edit", lambda p: False)
    monkeypatch.setattr(watcher, "append_change", lambda *a, **k: None)
    calls: list[tuple[str, str]] = []

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or vault).resolve()
        rel = Path(path).resolve().relative_to(resolved_root).as_posix()
        calls.append((rel, content))
        return None

    monkeypatch.setattr(watcher, "write_note_from_absolute", _fake_write)
    changed = watcher._ensure_uuid(note, {}, "Body")
    assert changed is False
    assert calls and calls[0][0] == "note.md"
    assert "uuid:" in calls[0][1]


def test_make_uri_handles_paths_outside_vault(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    other = tmp_path / "outside.md"
    other.write_text("Body", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    uri = watcher._make_uri(other)
    assert "obsidian://advanced-uri" in uri
    assert "filepath=outside.md" in uri
