from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.agents.panel.writeback import (
    annotate_action_ids,
    remove_actions_from_markdown,
    stable_action_id,
    upsert_executed_ids,
    write_receipts,
)
from app.agents.panel.parser import parse_panel
from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.intent import PanelActionIntent
from app.agents.panel_agent.planning import plan_panel_actions
from app.agents.panel_agent.settings import get_panel_agent_decider, get_panel_agent_pipeline
from app.agents.panel_agent.state import PanelAgentState
from app.agents.panel_agent.wiring import get_default_action_wiring
from app.components.settings.panel_actions_loader import load_panel_action_catalog
from app.events.panel import NoteRef, PanelIntentEvent, PanelLogEntry, PanelRuntimeActionResult
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import append_jsonl_outbox_event, coerce_outbox_event, write_outbox_event
from app.store.object_store import ObjectStore

logger = logging.getLogger(__name__)


def _resolve_outbox_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _write_db_outbox_events(events: Iterable[Any]) -> None:
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend != "pg" and not db_url:
        return
    for event in events:
        outbox_event = coerce_outbox_event(event, default_source="panel_agent.runtime")
        if outbox_event is None:
            continue
        try:
            write_outbox_event(outbox_event, idempotency_key=outbox_event.event_id)
        except Exception as exc:
            print(f"WARN: failed to enqueue DB outbox event {outbox_event.event}: {exc}")


def _persist_log(note: NoteRef, log_entry: PanelLogEntry) -> None:
    store = ObjectStore()
    existing = store.get_object(note.uuid)
    if existing is None:
        return
    payload = dict(existing.payload or {})
    logs = list(payload.get("panel_logs") or [])
    logs.append(log_entry.model_dump(mode="json"))
    payload["panel_logs"] = logs
    existing.payload = payload
    store.save_object(existing, emit_outbox=False, trace_id=log_entry.trace_id)


class PanelRuntimeResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    intent: PanelIntentEvent
    actions: list[PanelRuntimeActionResult] = Field(default_factory=list)
    emitted_events: list[Any] = Field(default_factory=list)
    log_entry: PanelLogEntry | None = None


def execute_panel_intent(intent_event: PanelIntentEvent, *, outbox_path: Path | None = None) -> PanelRuntimeResult:
    policy_flags = {"execution_mode": "watcher" if intent_event.source.trigger == "watcher" else "manual"}
    resolved_outbox = _resolve_outbox_path(outbox_path)
    catalog = load_panel_action_catalog()
    wiring = get_default_action_wiring()
    store = ObjectStore()
    note_obj = store.get_object(intent_event.payload.note.uuid)
    note_text = ""
    executed_ids: set[str] = set()
    if note_obj:
        payload = note_obj.payload or {}
        note_text = str(payload.get("raw_text") or payload.get("text") or "")
        executed_ids = set(payload.get("executed_action_ids") or [])

    actions = [action for action in intent_event.payload.actions if action.id not in executed_ids]
    payload = intent_event.payload.model_copy(update={"actions": list(actions)})
    intent_event = intent_event.model_copy(update={"payload": payload})
    panel_hints = [
        {"id": action.id, "label": action.label, "checked": action.checked} for action in actions
    ]
    vault_root_env = os.getenv("VAULT_ROOT")
    vault_root = Path(vault_root_env).expanduser() if vault_root_env else None
    initial_state = PanelAgentState(
        trace_id=intent_event.trace_id,
        note=intent_event.payload.note,
        panel=intent_event.payload.panel,
        actions=list(actions),
        intent_event=intent_event,
        action_catalog=catalog,
        action_wiring=wiring,
        note_content=note_text,
        panel_hints=panel_hints,
        executed_action_ids=sorted(executed_ids),
        policy_flags=policy_flags,
        vault_root=vault_root,
    )
    decider_mode = get_panel_agent_decider()
    state = run_panel_graph(initial_state, decider_mode=decider_mode)

    pipeline_mode = get_panel_agent_pipeline()
    if pipeline_mode == "planner":
        planned_action_ids: list[str] = []
        for result in state.action_results:
            if not result.checked or result.status not in {"triggered", "logged"}:
                continue
            if result.id not in planned_action_ids:
                planned_action_ids.append(result.id)
        if planned_action_ids:
            resolved_actions = [action for action in state.actions if action.id in planned_action_ids]
            state.panel_action_intent = PanelActionIntent(
                note=intent_event.payload.note,
                instruction=intent_event.payload.panel.instruction,
                actions=planned_action_ids,
                resolved_actions=resolved_actions,
                source="panel_agent",
            )
            plan_panel_actions(state.panel_action_intent, event_id=intent_event.event_id, trace_id=intent_event.trace_id)

    emitted_events = list(state.emitted_events or [])
    _write_db_outbox_events(emitted_events)
    for event in emitted_events:
        append_jsonl_outbox_event(resolved_outbox, event, default_source="panel_agent.runtime")
    if state.log_entry:
        _persist_log(intent_event.payload.note, state.log_entry)

    # --- Panel writeback: remove executed checkboxes and write receipts ---
    _apply_note_writeback(state, note_text, vault_root)

    return PanelRuntimeResult(
        intent=intent_event,
        actions=state.action_results,
        emitted_events=emitted_events,
        log_entry=state.log_entry,
    )


def _apply_note_writeback(
    state: PanelAgentState,
    original_note_text: str,
    vault_root: Path | None,
) -> None:
    """Remove executed checkboxes, write receipts, and persist to vault file.

    This mirrors the writeback contract that ``handle_note_update`` applies in the
    non-watcher path, ensuring the documented panel contract (checkbox removal +
    AI status receipt block) is honoured for watcher/worker-driven execution.
    """
    executed_labels: list[str] = []
    for result in state.action_results:
        if result.checked and result.status in {"triggered", "logged"}:
            executed_labels.append(result.label)

    if not executed_labels:
        return

    note_uuid = state.note.uuid
    note_path_str = state.note.path

    # Resolve the vault file path for writing.
    note_file: Path | None = None
    if note_path_str:
        candidate = Path(note_path_str)
        if candidate.is_absolute() and candidate.exists():
            note_file = candidate
        elif vault_root:
            candidate = vault_root / note_path_str
            if candidate.exists():
                note_file = candidate

    if note_file is None:
        logger.warning(
            "panel writeback skipped (cannot resolve note file) note_uuid=%s note_path=%s",
            note_uuid,
            note_path_str,
        )
        return

    # Re-read current file content to pick up any concurrent changes (e.g. uuid healing).
    try:
        current_text = note_file.read_text(encoding="utf-8")
    except OSError:
        logger.warning("panel writeback skipped (cannot read note) note_path=%s", note_file)
        return

    # Annotate checkbox lines with ai:id so removal works correctly.
    annotated = annotate_action_ids(current_text)

    # Build the set of ai:id annotation IDs to remove, mapping from label -> stable hash.
    ids_to_remove: set[str] = set()
    for label in executed_labels:
        ids_to_remove.add(stable_action_id(label))

    updated = remove_actions_from_markdown(annotated, ids_to_remove)

    # Build receipt lines.
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    receipts = [f"\u2705 {label} ({now_str})" for label in executed_labels]

    # Find preferred insert position (after last panel fence).
    parsed = parse_panel(updated)
    preferred_index = None
    if parsed.spans:
        _, end = parsed.spans[-1]
        preferred_index = end + 1

    updated = write_receipts(updated, receipts, preferred_index=preferred_index)

    # Write to disk.
    try:
        note_file.write_text(updated, encoding="utf-8")
    except OSError:
        logger.warning("panel writeback failed (write error) note_path=%s", note_file)
        return

    # Persist executed IDs so reruns are idempotent.
    upsert_executed_ids(note_uuid, [stable_action_id(label) for label in executed_labels])

    # Refresh companion content_hash so it reflects the post-writeback content.
    _refresh_companion_hash(note_uuid, updated, vault_root, note_file)

    logger.info(
        "panel writeback applied note_path=%s removed=%d receipts=%d",
        note_file,
        len(ids_to_remove),
        len(receipts),
    )


def _refresh_companion_hash(
    note_uuid: str,
    updated_text: str,
    vault_root: Path | None,
    note_file: Path,
) -> None:
    """Update the companion note's content_hash after writeback so it stays consistent."""
    if vault_root is None:
        return
    try:
        from app.services.companion_note import read_companion, write_companion
        from scripts.yaml_roundtrip import load_frontmatter

        companion = read_companion(vault_root, note_uuid)
        if companion is None:
            return
        _, body = load_frontmatter(updated_text)
        content = (body or updated_text).strip()
        new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if companion.content_hash == new_hash:
            return
        companion.content_hash = new_hash
        write_companion(vault_root, companion)
    except Exception:
        logger.debug("companion hash refresh skipped note_uuid=%s", note_uuid, exc_info=True)


__all__ = ["execute_panel_intent", "PanelRuntimeResult"]
