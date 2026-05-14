from __future__ import annotations

from pathlib import Path


def test_canvas_enabled_default_explicit() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "runtime.defaults.env"
    content = config_path.read_text(encoding="utf-8")
    assert "CANVAS_ENABLED=0" in content
