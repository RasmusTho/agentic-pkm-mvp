from __future__ import annotations

import fnmatch
from pathlib import Path


def parse_scope_glob(scope_glob: str) -> list[str]:
    raw = (scope_glob or "").strip()
    if not raw:
        return []
    if "," not in raw:
        return [raw]
    parts = [part.strip() for part in raw.split(",")]
    return [part for part in parts if part]


def matches_scope(rel_path: Path, scope_glob: str) -> bool:
    rel_str = str(rel_path)
    patterns = parse_scope_glob(scope_glob)
    if not patterns:
        return False
    return any(fnmatch.fnmatch(rel_str, pat) for pat in patterns)

