from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "search-service"
ALLOWED_PREFIXES = (
    "app/_legacy/",
)
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def _is_allowed(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(rel.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _should_skip(path: Path) -> bool:
    if path.suffix in SKIP_SUFFIXES:
        return True
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    return False


def test_no_search_service_provider() -> None:
    violations: list[str] = []
    for path in (ROOT / "app").rglob("*"):
        if not path.is_file():
            continue
        if _is_allowed(path) or _should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if TOKEN in text:
            for idx, line in enumerate(text.splitlines(), start=1):
                if TOKEN in line:
                    violations.append(f"{path.relative_to(ROOT)}:{idx}: {TOKEN}")
    assert not violations, "search-service provider should not be used:\n" + "\n".join(violations)
