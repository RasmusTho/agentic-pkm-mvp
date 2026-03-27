from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TOKENS = (
    "Inbox/**",
    "Inbox/_alpha_e2e",
    "📥 Inbox",
    "📥 Inbox/**",
)

ALLOWED_FILES = {
    "tests/guards/test_no_hardcoded_inbox_scope.py",
    "app/settings/default-vault-layout.yaml",
}

SCAN_PATHS = (
    "app",
    "scripts",
    "configs",
    "docker-compose.yaml",
    "docker-compose.watcher.yml",
    "docker-compose.override.yml",
)

SKIP_DIRS = {"__pycache__", ".git"}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for entry in SCAN_PATHS:
        candidate = ROOT / entry
        if candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend([p for p in candidate.rglob("*") if p.is_file()])
    return files


def test_no_hardcoded_inbox_scope_defaults() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for token in TOKENS:
            if token not in text:
                continue
            for ln, line in enumerate(text.splitlines(), start=1):
                if token in line:
                    violations.append(f"{rel}:{ln}: {token}")
    assert not violations, "Hardcoded inbox/scope defaults found:\n" + "\n".join(violations)
