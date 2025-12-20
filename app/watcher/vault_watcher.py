from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app.agents.panel.agent import handle_note_update
from app.agents.panel_agent.policy import watcher_may_run_panel
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings
from app.store.object_store import ObjectStore
from app.watcher.events import emit_watcher_run_event
from scripts.yaml_roundtrip import load_frontmatter

Snapshot = dict[str, float]
Summary = dict[str, object]


class OutboxPathError(ValueError):
    """Raised when the outbox path cannot be resolved."""


def _resolve_outbox_path(outbox_path: Path | None) -> Path | None:
    if outbox_path is not None:
        return Path(outbox_path)
    env_path = os.environ.get("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return None


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


def _scan_md_files(vault_root: Path) -> dict[str, float]:
    current: dict[str, float] = {}
    for path in sorted(vault_root.rglob("*.md")):
        try:
            rel = path.relative_to(vault_root)
        except Exception:
            continue
        if rel.parts and rel.parts[0] == "System" and rel.parts[1:2] == ("Metadata",):
            continue
        try:
            current[str(rel)] = path.stat().st_mtime
        except Exception:
            continue
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


def _write_outbox_events(outbox_path: Path | None, events: Iterable) -> int:
    if outbox_path is None:
        return 0
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with outbox_path.open("a", encoding="utf-8") as handle:
        for event in events:
            payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else None
            if payload is None:
                continue
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            written += 1
    return written


def compute_changes(
    vault_root: Path, snapshot: Snapshot
) -> tuple[list[Path], list[Path], Snapshot]:
    current = _scan_md_files(vault_root)
    changed: list[Path] = []
    deleted: list[Path] = []

    for rel_str, mtime in current.items():
        prev = snapshot.get(rel_str)
        if prev is None or prev != mtime:
            changed.append(vault_root / rel_str)

    for rel_str in snapshot:
        if rel_str not in current:
            deleted.append(vault_root / rel_str)

    return changed, deleted, current


def _emit_run_event(
    summary: Summary,
    *,
    vault_root: Path,
    snapshot_path: Path | None,
    outbox_path: Path | None,
    trigger: str,
) -> None:
    if outbox_path is None:
        return
    emit_watcher_run_event(
        summary,
        vault_root=vault_root,
        snapshot_path=snapshot_path,
        outbox_path=outbox_path,
        trigger=trigger,
    )


@dataclass
class VaultWatcherResult:
    changed: list[Path]
    deleted: list[Path]
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
    outbox_path: Path | None = None,
) -> tuple[Summary, list[str]]:
    try:
        import app.agents.panel.agent as panel_agent

        panel_agent._EXECUTED_FALLBACK.clear()
    except Exception:
        pass
    watcher = VaultWatcher(vault_root, snapshot_path=snapshot_path)
    result = watcher.run(save=False)
    resolved_outbox = _resolve_outbox_path(outbox_path)
    if resolved_outbox is None and not dry_run:
        raise OutboxPathError(
            "Outbox path is required for watcher runs; set INDEX_OUTBOX_PATH or pass --outbox-path."
        )
    action_mappings = load_panel_action_mappings()
    if not action_mappings:
        fallback_mapping = PanelActionMapping(
            text="Make this note evergreen",
            event_type="promote.intent.created",
            payload_template={"maturity": "evergreen"},
            action_id="promote.evergreen",
        )
        action_mappings = {
            "Make this note evergreen": fallback_mapping,
            "Gör denna anteckning evergreen": fallback_mapping,
        }

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
        _emit_run_event(
            summary,
            vault_root=vault_root,
            snapshot_path=watcher.snapshot_path,
            outbox_path=resolved_outbox,
            trigger="vault_watcher_run",
        )
        return summary, messages

    if not force and summary["changed"] > max_notes:
        summary["limit_exceeded"] = True
        summary["panel_skipped_limit"] = summary["changed"]
        messages.append(
            "Changed notes ("
            f"{summary['changed']}"
            f") exceed max-notes={max_notes}; aborting watcher run. "
            "Use --force to override."
        )
        _emit_run_event(
            summary,
            vault_root=vault_root,
            snapshot_path=watcher.snapshot_path,
            outbox_path=resolved_outbox,
            trigger="vault_watcher_run",
        )
        return summary, messages

    if dry_run:
        _emit_run_event(
            summary,
            vault_root=vault_root,
            snapshot_path=watcher.snapshot_path,
            outbox_path=resolved_outbox,
            trigger="vault_watcher_run",
        )
        return summary, messages

    summary["ingest_attempted"] = summary["changed"]
    ingest_summary = run_vault_alpha_ingest_paths(vault_root, result.changed, force=False)
    summary["ingested"] = ingest_summary.ingested
    summary["errors"] += ingest_summary.errors

    if not skip_panel and policy_allowed_paths:
        store = ObjectStore()
        for note_path in policy_allowed_paths:
            refreshed_frontmatter = _read_frontmatter(note_path)
            note_uuid = _note_uuid_from_frontmatter(refreshed_frontmatter)
            if not note_uuid:
                messages.append(
                    "Warning: unable to resolve uuid for "
                    f"{note_path}; skipping panel run."
                )
                summary["errors"] += 1
                continue

            _hydrate_store_with_markdown(note_uuid, note_path)
            current_markdown = ""
            try:
                current_markdown = note_path.read_text(encoding="utf-8")
            except Exception:
                messages.append(
                    f"Warning: unable to read {note_path}; skipping panel run."
                )
                summary["errors"] += 1
                continue

            stored = store.get_object(note_uuid)
            old_markdown = ""
            if stored:
                old_markdown = str((stored.payload or {}).get("raw_text") or "")

            panel_result = handle_note_update(
                note_uuid,
                old_markdown,
                current_markdown,
                action_mappings=action_mappings,
                note_path=str(note_path),
            )

            if panel_result.state.actions or panel_result.intents or panel_result.events:
                summary["panel_runs"] += 1

            summary["panel_promotions"] += len(
                [
                    ev
                    for ev in panel_result.events
                    if getattr(ev, "event", None) == "promote.intent.created"
                    or getattr(ev, "event_type", "") == "promote.intent.created"
                ]
            )

            if not emit_only and panel_result.updated_markdown != current_markdown:
                try:
                    note_path.write_text(panel_result.updated_markdown, encoding="utf-8")
                    _hydrate_store_with_markdown(note_uuid, note_path)
                except Exception:
                    messages.append(f"Warning: failed to write updates to {note_path}")
                    summary["errors"] += 1

            _write_outbox_events(resolved_outbox, panel_result.events)
    else:
        messages.append("Panel runtime skipped (no candidates or --skip-panel set).")

    watcher.refresh_snapshot()
    _emit_run_event(
        summary,
        vault_root=vault_root,
        snapshot_path=watcher.snapshot_path,
        outbox_path=resolved_outbox,
        trigger="vault_watcher_run",
    )
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
    outbox_path: Path | None = None,
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
            outbox_path=outbox_path,
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
    "OutboxPathError",
]
