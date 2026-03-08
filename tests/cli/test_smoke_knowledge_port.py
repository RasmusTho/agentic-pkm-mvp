from __future__ import annotations

import importlib
from pathlib import Path


smoke_module = importlib.import_module("app.cli.smoke")


def test_smoke_seed_and_cursor_write_via_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    writes: list[str] = []

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or vault).resolve()
        rel = Path(path).resolve().relative_to(resolved_root).as_posix()
        writes.append(rel)
        target = (resolved_root / rel).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr(smoke_module, "write_note_from_absolute", _fake_write)

    _, note_path = smoke_module._seed_note(vault)
    smoke_module._mark_cursor(note_path, vault)

    assert "PanelSmoke.md" in writes
    assert (vault / "PanelSmoke.md").exists()
