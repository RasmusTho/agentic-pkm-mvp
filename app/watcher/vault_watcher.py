from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


Snapshot = Dict[str, float]


def _default_snapshot_path(vault_root: Path) -> Path:
    return vault_root / ".agentic-pkm" / "vault_watcher_state.json"


def load_snapshot(path: Path) -> Snapshot:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_snapshot(path: Path, snapshot: Snapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def _scan_md_files(vault_root: Path) -> Dict[str, float]:
    current: Dict[str, float] = {}
    for path in sorted(vault_root.rglob("*.md")):
        try:
            rel = path.relative_to(vault_root)
        except Exception:
            continue
        # Skip metadata mirrors to avoid re-ingesting mirror files
        if rel.parts and rel.parts[0] == "System" and rel.parts[1:2] == ("Metadata",):
            continue
        current[str(rel)] = path.stat().st_mtime
    return current


def compute_changes(
    vault_root: Path, snapshot: Snapshot
) -> Tuple[List[Path], List[Path], Snapshot]:
    current = _scan_md_files(vault_root)
    changed: List[Path] = []
    deleted: List[Path] = []

    for rel_str, mtime in current.items():
        prev = snapshot.get(rel_str)
        if prev is None or prev != mtime:
            changed.append(vault_root / rel_str)

    for rel_str in snapshot:
        if rel_str not in current:
            deleted.append(vault_root / rel_str)

    return changed, deleted, current


@dataclass
class VaultWatcherResult:
    changed: List[Path]
    deleted: List[Path]
    snapshot: Snapshot


class VaultWatcher:
    def __init__(self, vault_root: Path, snapshot_path: Path | None = None) -> None:
        self.vault_root = vault_root.expanduser().resolve()
        self.snapshot_path = snapshot_path or _default_snapshot_path(self.vault_root)

    def run(self, *, save: bool = True) -> VaultWatcherResult:
        snapshot = load_snapshot(self.snapshot_path)
        changed, deleted, current = compute_changes(self.vault_root, snapshot)
        if save:
            save_snapshot(self.snapshot_path, current)
        return VaultWatcherResult(changed=changed, deleted=deleted, snapshot=current)

    def refresh_snapshot(self) -> Snapshot:
        current = _scan_md_files(self.vault_root)
        save_snapshot(self.snapshot_path, current)
        return current


__all__ = [
    "VaultWatcher",
    "VaultWatcherResult",
    "compute_changes",
    "load_snapshot",
    "save_snapshot",
]
