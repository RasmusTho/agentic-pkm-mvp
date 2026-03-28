from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_FILES = {
    Path(".env.example"),
    Path("config/runtime.defaults.env"),
    Path("config/eval.defaults.env"),
    Path("scripts/verify_runtime_guard.py"),
    Path("vault/@Settings/watchers.md"),
    Path("tests/guards/test_no_hardcoded_runtime_defaults.py"),
}
PATTERNS = (
    re.compile(r"postgresql://(?:app|postgres):(?:app|postgres)@"),
    re.compile(r"http://127\.0\.0\.1:11434"),
    re.compile(r"http://localhost:11434"),
    re.compile(r"http://host\.docker\.internal:11434/v1"),
    re.compile(r"\bsk-local\b"),
)


def _iter_files() -> list[Path]:
    roots = [
        ROOT / "app",
        ROOT / "scripts",
        ROOT / "docker-compose.yaml",
        ROOT / "docker-compose.override.yml",
        ROOT / "docker-compose.watcher.yml",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file())
    return files


def test_no_hardcoded_runtime_defaults() -> None:
    violations: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT)
        if rel in ALLOWED_FILES:
            continue
        if "__pycache__" in rel.parts:
            continue
        if rel.parts and rel.parts[0] in {"tests", "docs"}:
            continue
        if len(rel.parts) >= 2 and (rel.parts[0], rel.parts[1]) == ("scripts", "dev"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in PATTERNS:
            if pattern.search(text):
                violations.append(f"{rel}: {pattern.pattern}")
                break
    assert not violations, "Hardcoded runtime defaults found:\n" + "\n".join(violations)
