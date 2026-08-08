"""Regression coverage for the sanctioned resource-bounded ``not pg`` fallback (#4016)."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_WORKFLOW = REPO_ROOT / "docs" / "development" / "DEV_WORKFLOW.md"


def test_not_pg_fallback_is_documented() -> None:
    """The fallback must remain full-selection, leased, and Companion-import-safe."""
    text = DEV_WORKFLOW.read_text(encoding="utf-8")

    assert "### Resource-bounded local `not pg` fallback" in text
    assert "single pytest process exhausts a host resource" in text
    assert "same `not pg` marker selection" in text
    assert "--resource pytest-not-pg" in text
    assert ' -m "not pg"' in text
    assert "-mindepth 1 -maxdepth 1" in text
    assert ' -type f -name "test_*.py"' in text
    assert "companion-ui/companion-app" in text
    assert "Do not add\none-off path exports to Issue or PR handoffs." in text
    assert "uncovered shard as a validation gap" in text
