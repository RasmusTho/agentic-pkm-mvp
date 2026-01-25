from __future__ import annotations

from pathlib import Path

import pytest

from app.settings.panel_actions_settings import load_panel_actions_settings


def test_panel_actions_catalog_empty_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "panel-actions.md"
    empty.write_text("---\nmappings: []\n---\n", encoding="utf-8")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(empty))
    with pytest.raises(ValueError, match="panel action catalog is empty"):
        load_panel_actions_settings()
