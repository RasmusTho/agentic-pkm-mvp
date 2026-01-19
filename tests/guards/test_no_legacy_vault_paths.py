from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ("@Inbox", "@Desk", "@System")
ALLOWED_PREFIXES = (
    "app/_legacy/",
    "docs/LEGACY_",
)
ALLOWED_FILES = (
    "tests/guards/test_no_legacy_vault_paths.py",
)
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_FILES = {".DS_Store"}
SCAN_PATHS = (
    "app",
    "docs",
    "scripts",
    "tests",
    "configs",
    "vault",
    "docker-compose.yaml",
)


def _is_allowed(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel in ALLOWED_FILES:
        return True
    return any(rel.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _should_skip(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    return False


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for entry in SCAN_PATHS:
        candidate = ROOT / entry
        if candidate.is_file():
            files.append(candidate)
            continue
        if candidate.is_dir():
            files.extend([p for p in candidate.rglob("*") if p.is_file()])
    return files


def test_no_legacy_vault_paths() -> None:
    violations: list[str] = []
    for path in _iter_files():
        if _is_allowed(path) or _should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for token in TOKENS:
            if token not in text:
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                if token in line:
                    violations.append(f"{path.relative_to(ROOT)}:{idx}: {token}")
    assert not violations, "Legacy vault paths found:\n" + "\n".join(violations)
