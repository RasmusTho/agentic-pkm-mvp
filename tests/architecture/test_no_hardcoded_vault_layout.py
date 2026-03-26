from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.not_pg


_FORBIDDEN_LITERALS = [
    "📥 Inbox",
    "Inbox",
    "⚙️ System",
    "System-changes.md",
]


_SKIP_DIRS = {
    # Explicitly legacy/dev-only code; not part of the runtime watcher/worker chain.
    ("app", "_legacy"),
    ("scripts", "dev"),
}

_SKIP_FILES = {
    # Packaged product template consumed via app.settings.default_vault_layout.
    Path("app/settings/default-vault-layout.yaml"),
}


def _should_skip(rel: Path) -> bool:
    if rel in _SKIP_FILES:
        return True
    parts = rel.parts
    if len(parts) >= 2 and (parts[0], parts[1]) in _SKIP_DIRS:
        return True
    return False


def _iter_source_files(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / "app",
        repo_root / "scripts",
        repo_root / "configs",
        repo_root / "docker-compose.yaml",
        repo_root / "docker-compose.watcher.yml",
    ]

    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".svg"}:
                continue
            if path.name.startswith("."):
                continue
            files.append(path)
    return sorted(set(files))


def test_repo_has_no_hardcoded_vault_layout_literals() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []

    for path in _iter_source_files(repo_root):
        # Tests/docs are allowed to use illustrative examples; this guard is for
        # runtime code + operator scripts + runtime wiring.
        rel = path.relative_to(repo_root)
        if rel.parts and rel.parts[0] in {"tests", "docs"}:
            continue
        if _should_skip(rel):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for literal in _FORBIDDEN_LITERALS:
            if literal in text:
                offenders.append(f"{rel}: contains {literal!r}")

    assert not offenders, "Hardcoded vault layout literals found:\n" + "\n".join(offenders)
