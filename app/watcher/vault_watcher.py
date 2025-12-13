from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from app.agents.panel_agent.policy import watcher_may_run_panel
from app.cli.panel import run_panels_for_uuids
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.store.object_store import ObjectStore
from scripts.yaml_roundtrip import load_frontmatter


Snapshot = Dict[str, float]
Summary = Dict[str, object]


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


def _read_frontmatter(note_path: Path) -> dict:
    try:
        frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
        if not isinstance(frontmatter, dict):
            return {}
        return frontmatter
    except Exception:
        return {}


def _note_uuid_from_frontmatter(frontmatter: dict) -> str | None:
    raw = frontmatter.get("uuid") or ""
    value = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    return value or None


def _hydrate_store_with_markdown(note_uuid: str, note_path: Path) -> None:
    try:
        markdown = note_path.read_text(encoding="utf-8")
    except Exception:
        return
    store = ObjectStore()
    obj = store.get_object(note_uuid)
    if obj is None:
        return
    payload = dict(obj.payload or {})
    payload["raw_text"] = markdown
    obj.payload = payload
    store.save_object(obj, emit_outbox=False, trace_id=None)


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


def run_watcher_tick(
    *,
    vault_root: Path,
    snapshot_path: Path | None,
    skip_panel: bool,
    emit_only: bool,
    dry_run: bool,
    max_notes: int,
    force: bool,
) -> Tuple[Summary, list[str]]:
    watcher = VaultWatcher(vault_root, snapshot_path=snapshot_path)
    result = watcher.run(save=False)

    summary: Summary = {
        "changed": len(result.changed),
        "ingest_attempted": 0,
        "ingested": 0,
        "panel_candidates": 0,
        "panel_runs": 0,
        "panel_promotions": 0,
        "panel_skipped_policy": 0,
        "panel_skipped_limit": 0,
        "errors": 0,
        "dry_run": dry_run,
        "limit_exceeded": False,
        "snapshot_path": str(watcher.snapshot_path),
    }
    messages: list[str] = []

    policy_allowed_paths: list[Path] = []
    for path in result.changed:
        frontmatter = _read_frontmatter(path)
        note_uuid = _note_uuid_from_frontmatter(frontmatter)
        if watcher_may_run_panel(frontmatter):
            policy_allowed_paths.append(path)
        else:
            summary["panel_skipped_policy"] += 1

    summary["panel_candidates"] = len(policy_allowed_paths)

    if summary["changed"] == 0:
        if not dry_run:
            watcher.refresh_snapshot()
        return summary, messages

    if not force and summary["changed"] > max_notes:
        summary["limit_exceeded"] = True
        summary["panel_skipped_limit"] = summary["changed"]
        messages.append(
            f"Changed notes ({summary['changed']}) exceed max-notes={max_notes}; aborting watcher run. "
            "Use --force to override."
        )
        return summary, messages

    if dry_run:
        return summary, messages

    summary["ingest_attempted"] = summary["changed"]
    ingest_summary = run_vault_alpha_ingest_paths(vault_root, result.changed, force=False)
    summary["ingested"] = ingest_summary.ingested
    summary["errors"] += ingest_summary.errors

    if not skip_panel and policy_allowed_paths:
        panel_targets: list[str] = []
        for note_path in policy_allowed_paths:
            refreshed_frontmatter = _read_frontmatter(note_path)
            note_uuid = _note_uuid_from_frontmatter(refreshed_frontmatter)
            if not note_uuid:
                messages.append(f"Warning: unable to resolve uuid for {note_path}; skipping panel run.")
                summary["errors"] += 1
                continue
            _hydrate_store_with_markdown(note_uuid, note_path)
            panel_targets.append(note_uuid)
        processed, with_panels, promotions, errors, panel_messages = run_panels_for_uuids(
            tuple(panel_targets), emit_only=emit_only
        )
        messages.extend(panel_messages)
        summary["panel_runs"] = with_panels
        summary["panel_promotions"] = promotions
        summary["errors"] += errors
    else:
        messages.append("Panel runtime skipped (no candidates or --skip-panel set).")

    watcher.refresh_snapshot()
    return summary, messages


def run_watcher_daemon(
    *,
    vault_root: Path,
    snapshot_path: Path | None,
    skip_panel: bool,
    emit_only: bool,
    dry_run: bool,
    max_notes: int,
    force: bool,
    poll_seconds: int = 30,
    cooldown_seconds: int = 10,
    max_loops: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_tick: Callable[[Summary, list[str]], None] | None = None,
) -> list[Summary]:
    """Run watcher ticks in a loop; intended for CLI daemon."""

    summaries: list[Summary] = []
    loops = 0
    while True:
        summary, messages = run_watcher_tick(
            vault_root=vault_root,
            snapshot_path=snapshot_path,
            skip_panel=skip_panel,
            emit_only=emit_only,
            dry_run=dry_run,
            max_notes=max_notes,
            force=force,
        )
        summaries.append(summary)
        if on_tick:
            on_tick(summary, messages)
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return summaries
        delay = cooldown_seconds if summary.get("changed", 0) else poll_seconds
        sleep_fn(delay)


__all__ = [
    "VaultWatcher",
    "VaultWatcherResult",
    "compute_changes",
    "load_snapshot",
    "save_snapshot",
    "run_watcher_tick",
    "run_watcher_daemon",
]
