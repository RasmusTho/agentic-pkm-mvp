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


def _scope_prefix(pattern: str) -> str:
    wildcard_chars = {"*", "?", "["}
    limit = len(pattern)
    for idx, char in enumerate(pattern):
        if char in wildcard_chars:
            limit = idx
            break
    return pattern[:limit].rstrip("/")


def derive_scope_roots(vault_root: Path, scope_glob: str) -> list[Path]:
    patterns = parse_scope_glob(scope_glob)
    if not patterns:
        return [vault_root]

    prefixes = [_scope_prefix(pattern) for pattern in patterns]
    if not any(prefixes):
        return [vault_root]

    unique_prefixes: list[str] = []
    for prefix in prefixes:
        if not prefix:
            continue
        if prefix not in unique_prefixes:
            unique_prefixes.append(prefix)

    if not unique_prefixes:
        return [vault_root]

    if len(unique_prefixes) == 1:
        candidate = vault_root / unique_prefixes[0]
        if not candidate.exists() or not candidate.is_dir():
            raise FileNotFoundError(f"Scan root missing: {candidate}")
        resolved_vault = vault_root.resolve()
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_vault):
            raise ValueError(f"Scan root {resolved_candidate} must live under vault root {resolved_vault}")
        return [candidate]

    roots: list[Path] = []
    resolved_vault = vault_root.resolve()
    for prefix in unique_prefixes:
        candidate = vault_root / prefix
        if not candidate.exists() or not candidate.is_dir():
            raise FileNotFoundError(f"Scan root missing: {candidate}")
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_vault):
            raise ValueError(f"Scan root {resolved_candidate} must live under vault root {resolved_vault}")
        roots.append(candidate)
    return roots


def matches_scope(rel_path: Path, scope_glob: str) -> bool:
    rel_str = str(rel_path)
    patterns = parse_scope_glob(scope_glob)
    if not patterns:
        return False
    return any(fnmatch.fnmatch(rel_str, pat) for pat in patterns)
