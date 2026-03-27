from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app.agents.panel.agent import handle_note_update
from app.agents.panel.filters import strip_ai_panels
from app.agents.panel_agent.policy import watcher_panel_candidate
from app.components.concurrency import DedupTaskQueue, OptimisticWriteGuard, SystemClock, VersionMismatch
from app.ingest import vault_alpha as vault_alpha
from app.services.companion_note import find_companion_by_content_hash, read_companion
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings
from app.settings.watcher_settings import load_watcher_settings, resolve_auto_exec_enabled
from app.store.object_store import ObjectStore
from app.watcher.events import emit_watcher_run_event
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter

Snapshot = dict[str, float]
Summary = dict[str, object]

_PANEL_POLICY_ID = "panel_auto"
_DEDUP_QUEUE = DedupTaskQueue(SystemClock(), ttl_seconds=300.0)
_WRITE_GUARD = OptimisticWriteGuard()


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


def _note_uuid_from_frontmatter(
    frontmatter: dict,
    *,
    rel_path: Path | None = None,
    vault_root: Path | None = None,
    note_path: Path | None = None,
    body: str | None = None,
) -> str | None:
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    frontmatter_uuid = vault_alpha._normalize_uuid(
        frontmatter.get("uuid") or frontmatter.get("id") or ""
    )
    if frontmatter_uuid:
        return frontmatter_uuid

    companion_uuid = ""
    if vault_root is not None and rel_path is not None:
        # Direct O(1) lookup — companion is keyed by UUID, so we need frontmatter_uuid
        # (already extracted above). If found, use companion's uuid as identity anchor.
        companion = read_companion(vault_root, frontmatter_uuid) if frontmatter_uuid else None
        companion_uuid = companion.uuid if companion else ""
    if companion_uuid:
        return companion_uuid

    if vault_root is not None and rel_path is not None and note_path is not None and body is not None:
        stripped_text = strip_ai_panels(body).strip()
        text_sha256 = (
            hashlib.sha256(stripped_text.encode("utf-8")).hexdigest() if stripped_text else ""
        )
        if text_sha256:
            found = find_companion_by_content_hash(vault_root, text_sha256)
            if found:
                return found.uuid

    if rel_path is None:
        return None
    return str(uuid.uuid5(vault_alpha._VAULT_NOTE_UUID_NAMESPACE, rel_path.as_posix()))


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


def _content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _executed_action_ids_by_label(panel_result) -> dict[str, str]:
    executed_by_label: dict[str, str] = {}
    for event in getattr(panel_result, 'events', []):
        event_type = getattr(event, 'event', getattr(event, 'event_type', ''))
        if event_type != 'panel.intent.executed':
            continue
        payload = getattr(event, 'payload', {}) or {}
        for action in payload.get('actions', []):
            label = action.get('label')
            action_id = action.get('id')
            if label and action_id:
                executed_by_label[label] = action_id
    return executed_by_label


def _canonical_action_ids_by_text(panel_result) -> dict[str, str]:
    canonical: dict[str, str] = {}
    for event in getattr(panel_result, 'events', []):
        event_type = getattr(event, 'event', getattr(event, 'event_type', ''))
        if event_type != 'promote.intent.created':
            continue
        payload = getattr(event, 'payload', {}) or {}
        action_text = payload.get('action_text')
        if not action_text:
            action = payload.get('action') or {}
            action_text = action.get('label')
        action_id = payload.get('action_id') or (payload.get('action') or {}).get('id')
        if action_text and action_id:
            canonical[action_text] = action_id
    return canonical


def _disallowed_actions(
    panel_result,
    mappings,
    allowed_action_ids,
) -> list[tuple[str, str | None]]:
    executed_ids = _executed_action_ids_by_label(panel_result)
    canonical_ids = _canonical_action_ids_by_text(panel_result)
    disallowed: list[tuple[str, str | None]] = []
    state_actions = getattr(getattr(panel_result, 'state', None), 'actions', [])
    for action in state_actions:
        if not getattr(action, 'checked', False) or not getattr(action, 'text', None):
            continue
        action_id: str | None = None
        if action.text and mappings:
            mapping = mappings.get(action.text)
            if mapping:
                action_id = getattr(mapping, 'action_id', None)
        if not action_id and action.text:
            action_id = executed_ids.get(action.text)
        if not action_id and action.text:
            action_id = canonical_ids.get(action.text)
        canonical_id = action_id if action_id and '.' in action_id else None
        if canonical_id and canonical_id not in allowed_action_ids:
            disallowed.append((action.text, canonical_id))
    return disallowed


def _build_dedup_key(policy_id: str, rel_path: Path, content_hash: str) -> str:
    return f"watcher:{policy_id}:{rel_path.as_posix()}:{content_hash}"


def _auto_exec_enabled(vault_root: Path) -> bool:
    return resolve_auto_exec_enabled(vault_root=vault_root)


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
    watcher_settings = load_watcher_settings(vault_root)
    allowed_action_ids = {aid for aid in watcher_settings.allowed_actions if aid}
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
        "panel_skipped_auto_exec": 0,
        "panel_skipped_allowed_actions": 0,
        "applied_actions": 0,
        "skipped_dedup": 0,
        "skipped_idempotent": 0,
        "skipped_writes_blocked": 0,
        "errors": 0,
        "dry_run": dry_run,
        "limit_exceeded": False,
        "snapshot_path": str(watcher.snapshot_path),
    }
    messages: list[str] = []

    policy_allowed_paths: list[Path] = []
    for path in result.changed:
        rel_path = path.relative_to(vault_root)
        try:
            raw_markdown = path.read_text(encoding="utf-8")
        except Exception:
            summary["errors"] += 1
            messages.append(f"Warning: unable to read {rel_path}; skipping watcher policy evaluation.")
            continue

        try:
            frontmatter, _ = load_frontmatter(raw_markdown)
        except Exception:
            frontmatter = {}
        if not isinstance(frontmatter, dict):
            frontmatter = {}

        if watcher_panel_candidate(frontmatter, raw_markdown):
            policy_allowed_paths.append(path)
        else:
            summary["panel_skipped_policy"] += 1
            messages.append(f"Watcher policy denies auto-run for {rel_path}")

    summary["panel_candidates"] = len(policy_allowed_paths)

    auto_exec_enabled = _auto_exec_enabled(vault_root)
    if not auto_exec_enabled and not skip_panel:
        if policy_allowed_paths:
            summary["panel_skipped_auto_exec"] += len(policy_allowed_paths)
            messages.append("Watcher auto-exec disabled (WATCHER_AUTO_EXEC=1 required); skipping panel runtime.")
        skip_panel = True

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
            rel_path = note_path.relative_to(vault_root)
            current_markdown = ""
            try:
                current_markdown = note_path.read_text(encoding="utf-8")
            except Exception:
                messages.append(
                    f"Warning: unable to read {note_path}; skipping panel run."
                )
                summary["errors"] += 1
                continue

            frontmatter, body = load_frontmatter(current_markdown)
            if not isinstance(frontmatter, dict):
                frontmatter = {}
            note_uuid = _note_uuid_from_frontmatter(
                frontmatter,
                rel_path=rel_path,
                vault_root=vault_root,
                note_path=note_path,
                body=body,
            )
            if not note_uuid:
                messages.append(
                    "Warning: unable to resolve uuid for "
                    f"{note_path}; skipping panel run."
                )
                summary["errors"] += 1
                continue

            content_hash = _content_hash(current_markdown)
            dedup_key = _build_dedup_key(_PANEL_POLICY_ID, rel_path, content_hash)
            if not _DEDUP_QUEUE.try_acquire(dedup_key):
                summary["skipped_dedup"] += 1
                messages.append(f"Watcher dedup skip for {rel_path} (key={dedup_key})")
                continue

            try:
                try:
                    DEFAULT_WRITE_GUARD.assert_writes_allowed("vault watcher auto-exec")
                except WritesBlockedError as exc:
                    summary["skipped_writes_blocked"] += 1
                    messages.append(f"Watcher auto-exec blocked for {rel_path}: {exc}")
                    continue

                _hydrate_store_with_markdown(note_uuid, note_path)
                expected_version = _WRITE_GUARD.compute_version(current_markdown.encode("utf-8"))

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

                disallowed_actions = _disallowed_actions(
                    panel_result,
                    action_mappings,
                    allowed_action_ids,
                )
                if disallowed_actions:
                    summary['panel_skipped_allowed_actions'] += len(disallowed_actions)
                    disallowed_desc = ', '.join(
                        f"{text}({aid or 'unspecified'})" for text, aid in disallowed_actions
                    )
                    allowed_list = sorted(allowed_action_ids)
                    messages.append(
                        f"Watcher auto-run blocked for {rel_path}: actions {disallowed_desc} not in allowed set {allowed_list}."
                    )
                    continue

                if panel_result.state.actions or panel_result.intents or panel_result.events:
                    summary["panel_runs"] += 1

                applied_actions = sum(
                    1 for intent in panel_result.intents if getattr(intent, "kind", None) == "action_triggered"
                )
                summary["applied_actions"] += applied_actions

                checked_actions = [
                    action for action in panel_result.state.actions if action.checked and action.text
                ]
                if checked_actions and applied_actions == 0:
                    summary["skipped_idempotent"] += len(checked_actions)

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
                        DEFAULT_WRITE_GUARD.assert_writes_allowed("vault watcher panel write")
                        _WRITE_GUARD.write_if_unchanged(
                            note_path,
                            expected_version,
                            panel_result.updated_markdown,
                        )
                        _hydrate_store_with_markdown(note_uuid, note_path)
                    except VersionMismatch:
                        messages.append(f"Warning: stale write prevented for {note_path}")
                        summary["errors"] += 1
                    except WritesBlockedError:
                        raise
                    except Exception:
                        messages.append(f"Warning: failed to write updates to {note_path}")
                        summary["errors"] += 1

                _write_outbox_events(resolved_outbox, panel_result.events)
            finally:
                _DEDUP_QUEUE.release(dedup_key)
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
