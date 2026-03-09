from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from app.ports.filesystem_vault_adapter import FilesystemVaultAdapter
from app.ports.vault_port import DummyVaultPort, VaultPort


Factory = Callable[[Path, pytest.MonkeyPatch], VaultPort]


def _dummy_factory(_tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> DummyVaultPort:
    return DummyVaultPort()


def _filesystem_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FilesystemVaultAdapter:
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.active_edit", lambda _path: False)
    monkeypatch.setattr("app.ports.filesystem_vault_adapter.append_change", lambda *a, **k: None)
    return FilesystemVaultAdapter(vault_root=tmp_path, backend_writes_enabled=False)


@pytest.mark.parametrize(
    ("factory", "persists_writes"),
    [(_dummy_factory, False), (_filesystem_factory, True)],
)
def test_vault_port_contract_uuid_write_read_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, factory: Factory, persists_writes: bool
) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body", encoding="utf-8")
    port = factory(tmp_path, monkeypatch)

    read1 = port.read_note(note)
    assert read1.path == note
    assert read1.body == "Body"
    assert "uuid" not in (read1.frontmatter or {})

    ensured = port.ensure_uuid(read1, expected_mtime_ns=read1.mtime_ns)
    assert ensured.deferred is False
    assert ensured.uuid_value

    if persists_writes:
        read2 = port.read_note(note)
        assert str(read2.frontmatter.get("uuid") or "").strip() == ensured.uuid_value
        write_result = port.write_frontmatter(note, read2.frontmatter, read2.body, expected_mtime_ns=read2.mtime_ns)
        assert write_result is True


@pytest.mark.parametrize("factory", [_dummy_factory, _filesystem_factory])
def test_vault_port_contract_mtime_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, factory: Factory) -> None:
    note = tmp_path / "guard.md"
    note.write_text("---\nuuid: u-1\n---\n\nBody", encoding="utf-8")
    port = factory(tmp_path, monkeypatch)
    read1 = port.read_note(note)

    note.write_text("---\nuuid: u-1\n---\n\nChanged", encoding="utf-8")
    wrote = port.write_frontmatter(note, {"uuid": "u-1"}, "Body", expected_mtime_ns=read1.mtime_ns)
    assert wrote is False
