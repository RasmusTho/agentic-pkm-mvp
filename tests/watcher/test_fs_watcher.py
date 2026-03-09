from __future__ import annotations

from importlib import reload
from pathlib import Path

import pytest

from app.ports.vault_port import EnsureUuidResult, NoteRead
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


class RecordingVaultPort:
    def __init__(self, *, defer_uuid: bool = False) -> None:
        self.defer_uuid = defer_uuid
        self.upserts: list[tuple[str, dict[str, object], str, bool, bool]] = []
        self.renames: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, str | None]] = []
        self.messages: list[tuple[str, str | None]] = []

    def read_note(self, path: Path) -> NoteRead:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(text)
        return NoteRead(path=path, frontmatter=frontmatter, body=body, mtime_ns=path.stat().st_mtime_ns)

    def ensure_uuid(self, note: NoteRead, *, expected_mtime_ns: int | None = None) -> EnsureUuidResult:
        if note.frontmatter.get("uuid"):
            return EnsureUuidResult(deferred=False, wrote=False, uuid_value=str(note.frontmatter["uuid"]))
        if self.defer_uuid:
            self.append_inbox_item(f"Deferred UUID injection for {note.path.name}")
            return EnsureUuidResult(deferred=True, wrote=False, uuid_value=None, reason="active_edit")
        note.frontmatter["uuid"] = "generated-uuid"
        self.write_frontmatter(note.path, note.frontmatter, note.body, expected_mtime_ns=expected_mtime_ns)
        self.append_inbox_item(f"Injected UUID in {note.path.name}", uri="obsidian://advanced-uri?vault=Vault")
        return EnsureUuidResult(deferred=False, wrote=True, uuid_value="generated-uuid")

    def write_frontmatter(
        self, path: Path, frontmatter: dict[str, object], body: str, *, expected_mtime_ns: int | None = None
    ) -> bool:
        path.write_text(dump_frontmatter(frontmatter, body), encoding="utf-8")
        return True

    def rename_note(self, uuid_value: str, new_path: Path) -> None:
        self.renames.append((uuid_value, str(new_path)))

    def delete_note(self, path: Path, *, uuid_value: str | None = None) -> None:
        self.deletes.append((str(path), uuid_value))

    def upsert_note_object(
        self, path: Path, frontmatter: dict[str, object], body: str, fm_changed: bool, body_changed: bool
    ) -> None:
        self.upserts.append((str(path), frontmatter, body, fm_changed, body_changed))

    def append_inbox_item(self, message: str, *, vault_path: Path | None = None, uri: str | None = None) -> None:
        self.messages.append((message, uri))


def _load_watcher(monkeypatch: pytest.MonkeyPatch, vault_dir: Path):
    monkeypatch.setenv("VAULT_DIR", str(vault_dir))
    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "TestVault")
    import scripts.fs_watcher as watcher  # type: ignore

    reload(watcher)
    watcher.STATE.clear()
    watcher.UUID_INDEX.clear()
    return watcher


def test_scan_injects_uuid_and_upserts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("Plain body", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    monkeypatch.setattr(watcher, "active_edit", lambda _: False)
    port = RecordingVaultPort()
    watcher.scan_once(port)

    assert port.upserts
    _, fm, _, _, _ = port.upserts[-1]
    assert "uuid" in fm
    assert any("obsidian://advanced-uri" in (uri or "") for _, uri in port.messages)
    assert "uuid:" in note.read_text(encoding="utf-8")


def test_rename_only_updates_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "alpha.md"
    note.write_text("---\nuuid: 1234\n---\n\nBody", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    monkeypatch.setattr(watcher, "active_edit", lambda _: False)
    port = RecordingVaultPort()
    watcher.scan_once(port)
    port.upserts.clear()
    port.renames.clear()

    renamed = vault / "beta.md"
    note.rename(renamed)
    watcher.scan_once(port)

    assert port.renames == [("1234", str(renamed))]
    assert not port.upserts


def test_active_edit_skips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("---\nuuid: 5678\n---\n\nBody", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    monkeypatch.setattr(watcher, "active_edit", lambda _: True)
    port = RecordingVaultPort()
    watcher.scan_once(port)

    assert not port.upserts
    assert port.messages
    assert "Deferred" in port.messages[0][0]


def test_uri_falls_back_to_default_vault_when_env_blank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


def test_make_uri_handles_paths_outside_vault(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    other = tmp_path / "outside.md"
    other.write_text("Body", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    uri = watcher._make_uri(other)
    assert "obsidian://advanced-uri" in uri
    assert "filepath=outside.md" in uri


def test_deleted_note_propagates_to_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("---\nuuid: dead-beef\n---\n\nBody", encoding="utf-8")

    watcher = _load_watcher(monkeypatch, vault)
    monkeypatch.setattr(watcher, "active_edit", lambda _: False)
    port = RecordingVaultPort()
    watcher.scan_once(port)
    note.unlink()
    watcher.scan_once(port)

    assert port.deletes
    deleted_path, deleted_uuid = port.deletes[-1]
    assert deleted_path.endswith("note.md")
    assert deleted_uuid == "dead-beef"
