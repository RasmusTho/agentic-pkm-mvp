from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.agents.panel.agent import handle_note_update
from app.config.database import runtime_database_is_named
from app.agents.panel.filters import strip_ai_panels
from app.agents.panel.writeback import strip_ai_status_block, upsert_executed_ids
from app.agents.panel_agent.policy import (
    watcher_may_run_panel,
    watcher_panel_candidate,
    watcher_panel_writeback_allowed,
)
from app.components.concurrency import DedupTaskQueue, SystemClock
from app.ingest import vault_alpha as vault_alpha
from app.services.companion_note import (
    find_companion_by_content_hash,
    find_companion_by_source_ref,
    read_companion,
)
from app.events.types import INGEST_OBJECT_DELETED
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import read_note_text_with_version
from app.knowledge.write_ops import write_note_from_absolute
from app.services.outbox import insert_object_and_outbox, self_owned_write_would_skip
from app.services.vault_sync import delete_note
from app.watcher.registry import db_outbox_required
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings
from app.settings.watcher_settings import load_watcher_settings, resolve_auto_exec_enabled
from app.objects import ObjectStore, canonical_event_identity, resolve_canonical_object_id
from app.watcher.events import emit_watcher_run_event
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError
from app.vault.manager import iter_vault_markdown_files
from scripts.yaml_roundtrip import load_frontmatter

Snapshot = dict[str, float]
Summary = dict[str, object]

_PANEL_POLICY_ID = "panel_auto"
_DEDUP_QUEUE = DedupTaskQueue(SystemClock(), ttl_seconds=300.0)
_DELETE_RECONCILIATION_RETRY_LIMIT = 3


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


def _unreconciled_deletions_path(snapshot_path: Path) -> Path:
    """Return the bounded retry state that must outlive bare snapshot refreshes."""
    return snapshot_path.with_name(f"{snapshot_path.name}.unreconciled-deletions.json")


def _load_unreconciled_deletions(snapshot_path: Path) -> dict[str, dict[str, object]]:
    path = _unreconciled_deletions_path(snapshot_path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    pending: dict[str, dict[str, object]] = {}
    for rel_path, value in raw.items():
        if not isinstance(rel_path, str) or not isinstance(value, dict):
            continue
        try:
            attempts = int(value.get("attempts", 0))
            observed_mtime = float(value["observed_mtime"])
        except (KeyError, TypeError, ValueError):
            continue
        status = str(value.get("status", "pending"))
        if status not in {"pending", "terminated"}:
            continue
        if attempts > 0 and attempts <= _DELETE_RECONCILIATION_RETRY_LIMIT:
            pending[rel_path] = {
                "attempts": attempts,
                "observed_mtime": observed_mtime,
                "status": status,
            }
    return pending


def _save_unreconciled_deletions(
    snapshot_path: Path, pending: dict[str, dict[str, object]]
) -> None:
    path = _unreconciled_deletions_path(snapshot_path)
    if not pending:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending, indent=2, sort_keys=True), encoding="utf-8")


def _snapshot_with_unreconciled_deletions(snapshot_path: Path, current: Snapshot) -> Snapshot:
    """Retain only bounded unresolved deletes across every snapshot writer.

    ``refresh_snapshot()`` has callers outside ``run_watcher_tick``.  Keeping
    this state in a sibling file and merging it at the writer boundary means a
    bare refresh cannot silently erase a retryable deletion.
    """
    retained = dict(current)
    for rel_path, entry in _load_unreconciled_deletions(snapshot_path).items():
        if entry["status"] == "pending":
            retained.setdefault(rel_path, float(entry["observed_mtime"]))
    return retained


def _discard_reappeared_unreconciled_deletions(snapshot_path: Path, current: Snapshot) -> None:
    """A recreated path is a new live observation, never an old delete retry."""
    pending = _load_unreconciled_deletions(snapshot_path)
    for rel_path in current:
        pending.pop(rel_path, None)
    _save_unreconciled_deletions(snapshot_path, pending)


def _terminal_unreconciled_deletions(snapshot_path: Path) -> list[str]:
    return [
        rel_path
        for rel_path, entry in _load_unreconciled_deletions(snapshot_path).items()
        if entry["status"] == "terminated"
    ]


def _clear_terminal_unreconciled_deletions(snapshot_path: Path) -> None:
    pending = _load_unreconciled_deletions(snapshot_path)
    for rel_path in _terminal_unreconciled_deletions(snapshot_path):
        pending.pop(rel_path, None)
    _save_unreconciled_deletions(snapshot_path, pending)


def _advance_terminal_delete_observations(snapshot_path: Path) -> None:
    """Acknowledge only terminal deletes without advancing changed-note cursors."""
    snapshot = load_snapshot(snapshot_path)
    for rel_path in _terminal_unreconciled_deletions(snapshot_path):
        snapshot.pop(rel_path, None)
    save_snapshot(snapshot_path, snapshot)


def _scan_md_files(vault_root: Path) -> dict[str, float]:
    current: dict[str, float] = {}
    for path in iter_vault_markdown_files(vault_root):
        try:
            rel = path.relative_to(vault_root)
        except Exception:
            continue
        if rel.parts and rel.parts[0] == "System" and rel.parts[1:2] == ("Metadata",):
            continue
        if rel.parts and rel.parts[0] == "_system":
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
        stripped_text = strip_ai_status_block(strip_ai_panels(body)).strip()
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


def _resolve_note_scope(frontmatter: dict[str, object], global_scope: str | None) -> str | None:
    for key in ("scope", "domain"):
        value = frontmatter.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return global_scope


def extract_context_dimensions_for_note(frontmatter: dict[str, object], *, global_scope: str | None = None) -> dict[str, object]:
    scope = _resolve_note_scope(frontmatter, global_scope)
    spheres = frontmatter.get("sphere_memberships")
    if not isinstance(spheres, list):
        spheres = []
    identity = frontmatter.get("situated_identity")
    if not isinstance(identity, str):
        identity = None
    return {
        "scope": scope,
        "sphere_memberships": [str(item) for item in spheres],
        "situated_identity": identity,
    }


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


def _resolve_watcher_run_log(vault_root: Path) -> Path:
    """Resolve the dedicated watcher.run telemetry log path.

    Priority: WATCHER_RUN_LOG_PATH env > watcher_settings.paths.watcher_run_log.
    """
    env_value = os.getenv("WATCHER_RUN_LOG_PATH", "").strip()
    if env_value:
        return Path(env_value).expanduser()
    try:
        return load_watcher_settings(vault_root).paths.watcher_run_log
    except Exception:
        return Path("tmp/watcher_run.jsonl")


def _emit_run_event(
    summary: Summary,
    *,
    vault_root: Path,
    snapshot_path: Path | None,
    outbox_path: Path | None,
    trigger: str,
) -> None:
    """Emit a watcher.run event to the DEDICATED telemetry log.

    NOTE: ignores outbox_path — watcher.run records must not go to
    index-outbox.jsonl (the index/embedding audit sink).  The telemetry
    sink is resolved from WATCHER_RUN_LOG_PATH / watcher_settings.
    """
    telemetry_log_path = _resolve_watcher_run_log(vault_root)
    emit_watcher_run_event(
        summary,
        vault_root=vault_root,
        snapshot_path=snapshot_path,
        telemetry_log_path=telemetry_log_path,
        trigger=trigger,
    )


@dataclass
class VaultWatcherResult:
    changed: list[Path]
    deleted: list[Path]
    snapshot: Snapshot


class VaultWatcher:
    def __init__(self, vault_root: Path, snapshot_path: Path | None = None) -> None:
        self.vault_root = vault_root.expanduser()
        self.snapshot_path = snapshot_path or _default_snapshot_path(self.vault_root)

    def run(self, *, save: bool = True) -> VaultWatcherResult:
        snapshot = load_snapshot(self.snapshot_path)
        changed, deleted, current = compute_changes(self.vault_root, snapshot)
        terminal = set(_terminal_unreconciled_deletions(self.snapshot_path))
        deleted = [path for path in deleted if path.relative_to(self.vault_root).as_posix() not in terminal]
        if save:
            _discard_reappeared_unreconciled_deletions(self.snapshot_path, current)
            save_snapshot(
                self.snapshot_path,
                _snapshot_with_unreconciled_deletions(self.snapshot_path, current),
            )
        return VaultWatcherResult(changed=changed, deleted=deleted, snapshot=current)

    def refresh_snapshot(self) -> Snapshot:
        current = _scan_md_files(self.vault_root)
        _discard_reappeared_unreconciled_deletions(self.snapshot_path, current)
        retained = _snapshot_with_unreconciled_deletions(self.snapshot_path, current)
        save_snapshot(self.snapshot_path, retained)
        return retained


_DeleteReconciliation = Literal["emitted", "superseded_by_rename", "not_queued"]


def _emit_watcher_delete_event(
    deleted_path: Path,
    *,
    rel_deleted: Path,
    vault_root: Path,
    observed_mtime: float | None,
) -> _DeleteReconciliation:
    """Emit the deletion tombstone for a note vault_sync.delete_note could
    not identify (no file_state row -- i.e. a note ingested only through the
    tick's vault-alpha path, which keys store rows by note uuid).

    Identity resolution mirrors vault-alpha ingest's own uuid derivation
    (``app.ingest.vault_alpha._derive_note_uuid``): the companion note, found
    by source_ref (it survives the source note's deletion), carries the
    canonical uuid; a note that never had a frontmatter/companion uuid was
    keyed by the deterministic uuid5 of its vault-relative path, which
    re-derives identically here. The payload is shaped exactly like
    vault_sync.delete_note's so the worker's handle_ingest_object_deleted
    consumes both indistinguishably. ``observed_mtime`` (the deleted
    version's last snapshotted mtime) scopes the outbox idempotency key to
    this filesystem observation: a crash-retried tick dedups, while a
    delete->recreate->delete cycle emits both deletes.

    Rename safety: this runs AFTER the tick's ingest of changed paths, and
    skips emission when the resolved identity is still alive at another
    path -- the ingest of the rename target already updated the companion's
    source_ref, and the tick's vector upsert for the same uuid is
    synchronous with no follow-up created-event, so an async purge here
    would wipe the freshly re-ingested vectors with nothing to restore
    them.

    Durability (#4214 D3): this path has no compensating JSONL sink, and its
    caller both increments ``deleted_purged`` and lets ``refresh_snapshot()``
    drop the path — so a *silent* skip here is permanent and unrecoverable (the
    note is gone from disk AND from the snapshot, the purge event never
    existed, and the deleted content stays indexed). Two things follow.

    **The write is required whenever a database is named.** ``required_db`` is
    the watcher's own required-delivery intent OR ``runtime_database_is_named``,
    so a runtime with an explicit DSN keeps the delivery semantics it has on
    ``main`` — the enqueue is attempted and an unreachable database raises
    loudly — instead of being silently skipped by the optional-write policy
    under ``STORE_BACKEND=memory``. #4214's constraint is explicit that a
    properly configured runtime (``STORE_BACKEND=pg`` *or an explicit DSN*)
    must not change delivery semantics. This also makes every outcome
    terminal: named+reachable commits, named+unreachable raises once and is
    recorded as an error, and an unnamed runtime has no durable queue and no
    durable projection, so nothing is owed.

    **The outcome is reported explicitly** rather than as a bare bool, so the
    caller cannot read a skip as a purge. Note these are strings — ``"not_queued"``
    is truthy — so a caller must compare, never test truthiness:

    - ``"emitted"`` — the tombstone reached the outbox (or deduped against an
      identical one already there); the caller may count the purge;
    - ``"superseded_by_rename"`` — no tombstone is owed, the identity is alive
      at a new path (the rename case above);
    - ``"not_queued"`` — the runtime names no database, so the optional write
      skipped and no event exists. The caller must NOT count a purge.

    A required enqueue that fails raises; the caller records it as an error and
    does not count a purge.

    An unlanded deletion is re-observable under #4468's bounded termination
    policy. The reconciliation loop, rather than this emission helper, owns
    the retry state and terminal receipt.
    """
    companion = find_companion_by_source_ref(vault_root, str(rel_deleted))
    companion_uuid = companion.uuid if companion else ""
    note_uuid = vault_alpha._derive_note_uuid("", companion_uuid, rel_deleted)
    canonical_object_id = resolve_canonical_object_id(note_uuid)
    live_companion = read_companion(vault_root, note_uuid)
    if live_companion is not None and live_companion.source_ref:
        live_path = vault_root / live_companion.source_ref
        if live_path.exists():
            # Rename: the same identity now lives at a new path that this
            # tick already (re)ingested -- purging would orphan it.
            return "superseded_by_rename"
    payload = {
        # Match delete_note's canonical payload identity. The legacy watcher
        # accepts a relative vault root, so `deleted_path` can otherwise be
        # relative while delete_note resolves it before fingerprinting.
        "path": str(deleted_path.resolve()),
        "deleted": True,
        "reason": "vault_note_deleted",
        # Match delete_note's logical producer identity. If delete_note
        # committed and the process crashed before the watcher advanced its
        # snapshot, retrying through this fallback derives the same outbox
        # idempotency key instead of creating a second tombstone.
        "source": "vault_sync.delete_note",
        **canonical_event_identity(canonical_object_id, note_uuid),
    }
    required_db = db_outbox_required() or runtime_database_is_named(os.environ)
    # Resolved from the same policy the write itself applies, BEFORE the call,
    # because the write's ``""`` return cannot distinguish "skipped, nothing
    # queued" from "deduped against a row already queued". The write still runs
    # either way — a skip opens no connection, so there is nothing to save by
    # short-circuiting, and the decision stays in exactly one place.
    would_skip = self_owned_write_would_skip(required_db=required_db)
    insert_object_and_outbox(
        payload,
        INGEST_OBJECT_DELETED,
        None,
        # delete_note's file_state mtime is a timezone-aware datetime. The
        # snapshot holds that same stat value as an epoch float, so normalize
        # it back to the service's exact string form before the outbox hashes
        # the observation. This keeps commit-before-cleanup crash replay in
        # the same idempotency domain as delete_note.
        observation=(
            str(datetime.fromtimestamp(observed_mtime, tz=timezone.utc))
            if observed_mtime is not None
            else None
        ),
        required_db=required_db,
    )
    return "not_queued" if would_skip else "emitted"


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
        "deleted": len(result.deleted),
        "deleted_purged": 0,
        "unreconciled_deletions_terminated": 0,
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
    recovered_terminal = _terminal_unreconciled_deletions(watcher.snapshot_path)
    if recovered_terminal:
        summary["unreconciled_deletions_terminated"] += len(recovered_terminal)
        messages.extend(
            "Warning: deletion reconciliation retry budget exhausted for "
            f"{rel_path}; recovered terminal report"
            for rel_path in recovered_terminal
        )

    def _finish_tick(*, preserve_changed_observations: bool = False) -> None:
        """Persist snapshot before its receipt, then retire reported terminals.

        A crash before the receipt leaves the terminal record durable and the
        next run re-reports it; a crash after the receipt but before cleanup is
        an at-least-once report, never a restarted retry budget.
        """
        if not dry_run:
            if preserve_changed_observations:
                _advance_terminal_delete_observations(watcher.snapshot_path)
            else:
                watcher.refresh_snapshot()
        _emit_run_event(
            summary,
            vault_root=vault_root,
            snapshot_path=watcher.snapshot_path,
            outbox_path=resolved_outbox,
            trigger="vault_watcher_run",
        )
        if not dry_run and _terminal_unreconciled_deletions(watcher.snapshot_path):
            _clear_terminal_unreconciled_deletions(watcher.snapshot_path)

    # Reconcile watcher-detected filesystem deletions (#2990): the watcher
    # never deletes vault files itself, only derived store rows. First
    # delegate to the same production seam app-initiated deletes use
    # (vault_sync.delete_note): identical file_state-by-path uuid resolution,
    # objects tombstoning, and INGEST_OBJECT_DELETED emission -- and its
    # idempotency (replaying a deletion for an already-purged path finds no
    # file_state row and no-ops). Notes ingested only through the tick's
    # vault-alpha path are keyed by note uuid WITHOUT a file_state row, so
    # delete_note cannot emit for them (returns False); for those,
    # _emit_watcher_delete_event resolves the identity the same way ingest
    # derives it (companion note by source_ref -- the durable path->uuid
    # mapping that survives the note's deletion -- else the deterministic
    # uuid5(rel_path) fallback) and emits a delete_note-compatible tombstone
    # event directly. Idempotent on replay: the outbox idempotency key is
    # scoped to this observation (the deleted version's last snapshotted
    # mtime). Only a tombstone that actually landed counts as a purge (#4214
    # D3). An unlanded one is retained in bounded retry state by #4468; all
    # snapshot writers merge that state, so a bare refresh cannot erase it.
    # Called
    # AFTER the tick's ingest
    # of changed paths, so a rename (delete(old) + result.changed entry for
    # the new path) resolves against the already-updated companion and the
    # liveness check in _emit_watcher_delete_event can skip purging an
    # identity that just re-ingested at a new path. Runs in every non-dry-run
    # exit path -- including changed==0 and limit-exceeded (the max-notes
    # limit bounds panel/ingest fan-out only). dry_run must not purge.

    def _reconcile_deletions() -> None:
        if dry_run or not result.deleted:
            return
        prior_snapshot = load_snapshot(watcher.snapshot_path)
        pending = _load_unreconciled_deletions(watcher.snapshot_path)
        for deleted_path in result.deleted:
            try:
                rel_deleted = deleted_path.relative_to(vault_root)
            except ValueError:
                rel_deleted = deleted_path
            # `rel_deleted` falls back to the absolute path when relative_to
            # raises, so look the observation up under both keys rather than
            # losing the retention mtime on that branch.
            observed_mtime = prior_snapshot.get(str(rel_deleted))
            if observed_mtime is None:
                observed_mtime = prior_snapshot.get(str(deleted_path))
            pending_key = rel_deleted.as_posix()
            unresolved = False
            try:
                # delete_note commits its event inside its own transaction, so
                # True is proof the tombstone landed. False means it could not
                # identify the note (no file_state row), not that a queue
                # rejected it — the watcher's own emitter resolves those.
                outcome: _DeleteReconciliation
                if delete_note(str(deleted_path)):
                    outcome = "emitted"
                else:
                    outcome = _emit_watcher_delete_event(
                        deleted_path,
                        rel_deleted=rel_deleted,
                        vault_root=vault_root,
                        observed_mtime=observed_mtime,
                    )
                # Only a tombstone that actually landed counts as a purge
                # (#4214 D3). A rename is terminal, but a missing queue is
                # explicitly unreconciled and must take the bounded retry path.
                if outcome == "emitted":
                    summary["deleted_purged"] += 1
                elif outcome == "not_queued":
                    unresolved = True
            except Exception:
                unresolved = True

            if not unresolved:
                pending.pop(pending_key, None)
                continue

            attempts = int(pending.get(pending_key, {}).get("attempts", 0)) + 1
            if attempts >= _DELETE_RECONCILIATION_RETRY_LIMIT:
                # The terminal record is intentionally an operator-visible
                # message rather than a permanently retained snapshot row.
                # The normal watcher.run receipt carries the matching counter.
                pending[pending_key] = {
                    "attempts": attempts,
                    "observed_mtime": float(observed_mtime or 0.0),
                    "status": "terminated",
                }
                summary["unreconciled_deletions_terminated"] += 1
                messages.append(
                    "Warning: deletion reconciliation retry budget exhausted for "
                    f"{rel_deleted}; reported and no longer retained"
                )
                continue

            # Keep only retryable observations. Each entry has at most two
            # future attempts, and refresh_snapshot() preserves it even when
            # called by a non-tick caller.
            pending[pending_key] = {
                "attempts": attempts,
                "observed_mtime": float(observed_mtime or 0.0),
                "status": "pending",
            }
            summary["errors"] += 1
            messages.append(f"Warning: unable to reconcile deletion for {rel_deleted}")
        _save_unreconciled_deletions(watcher.snapshot_path, pending)

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

        if (
            watcher_panel_candidate(frontmatter, raw_markdown)
            and watcher_may_run_panel(frontmatter)
            and watcher_panel_writeback_allowed(rel_path, vault_root=vault_root)
        ):
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
        _reconcile_deletions()
        _finish_tick()
        return summary, messages

    if not force and summary["changed"] > max_notes:
        _reconcile_deletions()
        summary["limit_exceeded"] = True
        summary["panel_skipped_limit"] = summary["changed"]
        messages.append(
            "Changed notes ("
            f"{summary['changed']}"
            f") exceed max-notes={max_notes}; aborting watcher run. "
            "Use --force to override."
        )
        _finish_tick(preserve_changed_observations=True)
        return summary, messages

    if dry_run:
        _finish_tick()
        return summary, messages

    summary["ingest_attempted"] = summary["changed"]
    try:
        ingest_summary = run_vault_alpha_ingest_paths(vault_root, result.changed, force=False)
    except WritesBlockedError as exc:
        # Guard-at-seam defense-in-depth (#2910): the ingest path's own
        # layout-ensure writes carry the registered "vault.layout_ensure"
        # bootstrap escape (app/vault/layout.py), so under the default guard
        # this branch is not reached for layout provisioning. It remains for
        # any OTHER WriteGuard-gated write inside ingest (e.g. a caller-side
        # "ensure uuid" heal) or a guard whose escape list was narrowed: a
        # blocked ingest degrades to the same skipped_writes_blocked
        # accounting the panel auto-exec loop below uses, never a crashed
        # watcher tick.
        summary["skipped_writes_blocked"] += 1
        summary["ingested"] = 0
        messages.append(f"Watcher ingest blocked by write guard: {exc}")
        ingest_summary = None
    if ingest_summary is not None:
        summary["ingested"] = ingest_summary.ingested
        summary["errors"] += ingest_summary.errors

    # After ingest: renames' new paths are re-ingested (companion source_ref
    # updated) before their old paths are reconciled -- see _reconcile_deletions.
    _reconcile_deletions()

    if not skip_panel and policy_allowed_paths:
        store = ObjectStore()
        for note_path in policy_allowed_paths:
            rel_path = note_path.relative_to(vault_root)
            if not watcher_panel_writeback_allowed(rel_path, vault_root=vault_root):
                summary["panel_skipped_policy"] += 1
                messages.append(
                    f"Watcher policy denies non-canonical writeback for {rel_path}"
                )
                continue
            try:
                current_markdown, expected_version = read_note_text_with_version(
                    note_path
                )
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

            # Filesystem/companion identity remains the retained vault UUID,
            # but every ObjectStore-facing panel operation must use the
            # canonical objects.id.  Historical rows may deliberately have
            # objects.uuid != objects.id after the #3510 cutover; using the
            # frontmatter UUID here would let panel writeback create a second
            # store_objects parent and split executed-action history.
            canonical_object_id = resolve_canonical_object_id(note_uuid)

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

                _hydrate_store_with_markdown(canonical_object_id, note_path)

                stored = store.get_object(canonical_object_id)
                old_markdown = ""
                if stored:
                    old_markdown = str((stored.payload or {}).get("raw_text") or "")

                panel_result = handle_note_update(
                    canonical_object_id,
                    old_markdown,
                    current_markdown,
                    action_mappings=action_mappings,
                    note_path=str(note_path),
                    persist_executed_ids=False,
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

                if emit_only:
                    created_events = [
                        event
                        for event in panel_result.events
                        if getattr(event, "event", None) == "panel.intent.created"
                    ]
                    _write_outbox_events(resolved_outbox, created_events)
                    continue

                if panel_result.updated_markdown != current_markdown:
                    if not watcher_panel_writeback_allowed(
                        rel_path,
                        vault_root=vault_root,
                    ):
                        messages.append(
                            f"Warning: panel write path changed for {note_path}"
                        )
                        summary["errors"] += 1
                        continue
                    try:
                        write_note_from_absolute(
                            note_path,
                            panel_result.updated_markdown,
                            vault_root=vault_root,
                            action="vault watcher panel write",
                            expected_version=expected_version,
                        )
                        _hydrate_store_with_markdown(canonical_object_id, note_path)
                    except KnowledgeWriteConflict as exc:
                        if (
                            exc.receipt is not None
                            and exc.receipt.outcome == "conflict_staged"
                        ):
                            messages.append(
                                f"Warning: stale write staged for {note_path}"
                            )
                        else:
                            messages.append(
                                f"Warning: indeterminate panel write for {note_path}"
                            )
                        summary["errors"] += 1
                        continue
                    except WritesBlockedError:
                        raise
                    except Exception:
                        messages.append(f"Warning: failed to write updates to {note_path}")
                        summary["errors"] += 1
                        continue

                if panel_result.executed_action_ids:
                    upsert_executed_ids(
                        canonical_object_id,
                        panel_result.executed_action_ids,
                    )

                applied_actions = sum(
                    1
                    for intent in panel_result.intents
                    if getattr(intent, "kind", None) == "action_triggered"
                )
                summary["applied_actions"] += applied_actions

                checked_actions = [
                    action
                    for action in panel_result.state.actions
                    if action.checked and action.text
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

                _write_outbox_events(resolved_outbox, panel_result.events)
            finally:
                _DEDUP_QUEUE.release(dedup_key)
    else:
        messages.append("Panel runtime skipped (no candidates or --skip-panel set).")

    _finish_tick()
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
