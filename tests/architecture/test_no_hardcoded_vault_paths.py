from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.not_pg


_USER_CONFIGURABLE_PATH_LITERALS = [
    "Design Handoff",
    "Design Handoff/Assets",
    "Design Handoff/Templates",
    "Design Handoff/Archive",
]

_ALLOWED_FILES = {
    # Default definitions and initial vault settings seed the user-configurable
    # values. Runtime consumers should resolve through VaultPathResolver.
    Path("app/vault/manager.py"),
    Path("app/vault/settings_service.py"),
    # The `vault init` CLI (#1991) only names "Design Handoff" in its module
    # docstring and click help text; the actual scaffolding delegates to
    # VaultManager.initialize_vault (allowed above), so no runtime path is
    # hardcoded here.
    Path("app/cli/vault.py"),
}


def _iter_app_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in (repo_root / "app").rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".svg"}:
            continue
        if path.name.startswith("."):
            continue
        files.append(path)
    return sorted(files)


def test_user_configurable_vault_paths_use_context() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []

    for path in _iter_app_files(repo_root):
        rel = path.relative_to(repo_root)
        if rel in _ALLOWED_FILES:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for literal in _USER_CONFIGURABLE_PATH_LITERALS:
            if literal in text:
                offenders.append(f"{rel}: contains {literal!r}")

    assert not offenders, "User-configurable vault paths must resolve through VaultContext/settings:\n" + "\n".join(
        offenders
    )
