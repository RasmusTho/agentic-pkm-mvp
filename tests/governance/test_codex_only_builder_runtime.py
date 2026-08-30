from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_BUILDER_RUNTIME_FILES = (
    REPO_ROOT / "app/builderops/epic_dispatch.py",
    REPO_ROOT / "app/builderops/cli.py",
)


def test_active_builder_runtime_is_codex_only() -> None:
    for path in ACTIVE_BUILDER_RUNTIME_FILES:
        source = path.read_text(encoding="utf-8").lower()
        assert "claude" not in source, path
        assert "anthropic" not in source, path

    process_map = (
        REPO_ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"
    ).read_text(encoding="utf-8")
    assert "### Current active Builder carrier" in process_map
    assert "Codex is the only active Builder worker carrier" in process_map
