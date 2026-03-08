from __future__ import annotations

import importlib
from pathlib import Path


smoke_module = importlib.import_module("app.cli.smoke")


def test_smoke_seed_and_cursor_write_via_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    writes: list[str] = []

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            writes.append(locator.path)
            target = (vault / locator.path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return None

    monkeypatch.setattr(smoke_module, "resolve_knowledge_port", lambda **kwargs: FakePort())

    _, note_path = smoke_module._seed_note(vault)
    smoke_module._mark_cursor(note_path, vault)

    assert "PanelSmoke.md" in writes
    assert (vault / "PanelSmoke.md").exists()
