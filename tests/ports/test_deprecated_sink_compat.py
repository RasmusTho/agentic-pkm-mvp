from __future__ import annotations

from pathlib import Path

from app.ports.pg_sink import PgSink
from app.ports.sink import DummySink


def test_dummy_sink_exposes_delete_note() -> None:
    sink = DummySink()
    sink.delete_note("/tmp/note.md", uuid_value="u1")
    assert sink._vault.deletes[-1] == ("/tmp/note.md", "u1")


def test_pg_sink_routes_delete_to_filesystem_adapter(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, str | None]] = []

    def _fake_delete(self, path: Path, *, uuid_value: str | None = None) -> None:  # type: ignore[no-untyped-def]
        calls.append((path, uuid_value))

    monkeypatch.setattr("app.ports.pg_sink.FilesystemVaultAdapter.delete_note", _fake_delete)
    sink = PgSink(vault_root=tmp_path)
    sink.delete_note(str(tmp_path / "gone.md"), uuid_value="u2")
    assert calls[-1] == (tmp_path / "gone.md", "u2")
