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
from app.events.schema import make_outbox_event
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import append_jsonl_outbox_event, coerce_outbox_event, write_outbox_event
from app.store.object_store import ObjectStore

logger = logging.getLogger(__name__)

# No-match dedup marker (issue #1012). Char class follows #979 pattern: [A-Za-z0-9_.-]+
_NO_MATCH_MARKER_TPL = "<!--ai:no-match={hash}-->"


def _no_match_marker(instruction: str) -> str:
    h = hashlib.sha256(instruction.encode("utf-8")).hexdigest()[:16]
    return _NO_MATCH_MARKER_TPL.format(hash=h)


def _has_no_match_marker(text: str, instruction: str) -> bool:
    return _no_match_marker(instruction) in text


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


def execute_panel_intent(
    intent_event: PanelIntentEvent,
    *,
    outbox_path: Path | None = None,
    allow_legacy_promotion_without_trust_verb: bool = False,
) -> PanelRuntimeResult:
    policy_flags = {
        "execution_mode": "watcher" if intent_event.source.trigger == "watcher" else "manual",
        "allow_legacy_promotion_without_trust_verb": allow_legacy_promotion_without_trust_verb,
    }
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

    original_action_count = len(list(intent_event.payload.actions))
    actions = [action for action in intent_event.payload.actions if action.id not in executed_ids]
    converged_rerun = bool(executed_ids) and original_action_count > 0 and not actions
    payload = intent_event.payload.model_copy(update={"actions": list(actions)})
    intent_event = intent_event.model_copy(update={"payload": payload})
    panel_hints = [
        {"id": action.id, "label": action.label, "checked": action.checked} for action in actions
    ]
    vault_root_env = os.getenv("VAULT_ROOT") or os.getenv("WATCHER_VAULT_PATH")
    vault_root = Path(vault_root_env).expanduser() if vault_root_env else None
    decider_mode = get_panel_agent_decider()
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
        decider_mode=decider_mode,
        converged_rerun=converged_rerun,
    )
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
    existing_topics = {
        getattr(event, "event", None) or getattr(event, "event_type", None)
        for event in emitted_events
    }
    for action in intent_event.payload.actions:
        if not action.checked:
            continue
        mapping = getattr(action, "mapping", None)
        downstream = getattr(mapping, "downstream_event", None) if mapping is not None else None
        if not downstream or downstream in existing_topics:
            continue
        emitted_events.append(
            make_outbox_event(
                event=downstream,
                payload={
                    "note_uuid": intent_event.payload.note.uuid,
                    "note_path": intent_event.payload.note.path,
                    "action_id": action.id,
                    "params": dict(getattr(mapping, "params", {}) or {}),
                },
                trace_id=intent_event.trace_id,
                source="panel_agent.runtime",
            )
        )
    if not emitted_events:
        for action in intent_event.payload.actions:
            if not action.checked:
                continue
            mapping = getattr(action, "mapping", None)
            downstream = getattr(mapping, "downstream_event", None) if mapping is not None else None
            if not downstream:
                continue
            emitted_events.append(
                make_outbox_event(
                    event=downstream,
                    payload={
                        "note_uuid": intent_event.payload.note.uuid,
                        "note_path": intent_event.payload.note.path,
                        "action_id": action.id,
                        "params": dict(getattr(mapping, "params", {}) or {}),
                    },
                    trace_id=intent_event.trace_id,
                    source="panel_agent.runtime",
                )
            )
    # Suppress duplicate no-match events when the instruction is unchanged (#1012).
    _instruction = intent_event.payload.panel.instruction or ""
    if _has_no_match_marker(note_text, _instruction):
        emitted_events = [
            e for e in emitted_events
            if not (
                getattr(e, "event", None) == "panel.action.logged"
                and (getattr(e, "payload", {}) or {}).get("reason") == "no_actions_matched"
            )
        ]

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


def _existing_panel_proposal_labels(markdown: str) -> set[str]:
    """Return the set of label texts already present as checkbox actions in the
    last panel block of ``markdown``. Used to decide which proposals are new and
    should trigger a fresh proposal receipt (#980).
    """
    lines = markdown.splitlines()
    panel_start = None
    panel_end = None
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip().lower()
        if "%%" in line and "ai" in line:
            if panel_end is None:
                panel_end = idx
            else:
                panel_start = idx
                break
    if panel_end is None or panel_start is None:
        return set()
    panel_text = "\n".join(lines[panel_start : panel_end + 1])
    parsed = parse_panel(panel_text)
    return {action.text.strip() for action in parsed.actions if action.text.strip()}


def _write_proposals_to_panel(markdown: str, proposed_labels: list[tuple[str, str]]) -> str:
    """Write proposed (unchecked) actions into the AI-åtgärder section of a panel.

    Finds the correct panel block and inserts proposals after existing checkboxes
    but before the panel end fence, ensuring they'll be parsed as actions on re-runs.
    """
    if not proposed_labels:
        return markdown

    lines = markdown.splitlines()

    # Find the last panel block (by looking for start/end fences from end to start).
    # This handles multiple panels by choosing the last one.
    panel_start = None
    panel_end = None
    actions_section_start = None

    # Scan backwards to find panel end fence.
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip().lower()
        if "%%" in line and "ai" in line:
            if panel_end is None:
                panel_end = idx
            else:
                panel_start = idx
                break

    if panel_end is not None and panel_start is not None:
        # Dedupe against the panel block being updated, not against all panels in the note.
        panel_text = "\n".join(lines[panel_start : panel_end + 1])
        parsed = parse_panel(panel_text)
        existing_ids = {action.action_id for action in parsed.actions if action.action_id}
        existing_labels = {action.text.strip() for action in parsed.actions if action.text.strip()}
    else:
        existing_ids = set()
        existing_labels = set()

    proposal_lines = []
    for action_id, label in proposed_labels:
        label_text = label.strip()
        stable_id = stable_action_id(label_text)
        if stable_id in existing_ids or label_text in existing_labels:
            continue
        # Mark governance-bearing proposals with a persistent marker so the
        # parser can re-surface them as `proposal_pending=True` on subsequent
        # passes. This prevents the LLM from auto-selecting an unchecked
        # proposed line on a later pass and bypassing the human gate (#979).
        proposal_lines.append(
            f"- [ ] {label_text} <!--ai:id={stable_id}--> <!--ai:proposed=979-->"
        )

    if not proposal_lines:
        return markdown

    if panel_end is None or panel_start is None:
        # No clear panel structure found; append at end (fallback).
        lines.extend(proposal_lines)
        return "\n".join(lines)

    # Find the AI-åtgärder / AI-actions heading within the panel.
    # Look for common action section headings (Swedish and English variants).
    for idx in range(panel_start, panel_end):
        line = lines[idx].strip().lower()
        if "åtgärd" in line or "action" in line:
            # This is likely the actions section heading.
            # Find the first checkbox line after this heading to insert after them.
            actions_section_start = idx
            break

    if actions_section_start is None:
        # No actions section found; insert before panel end fence.
        for proposal in reversed(proposal_lines):
            lines.insert(panel_end, proposal)
        return "\n".join(lines)

    # Find the position to insert: after the last checkbox in the actions section,
    # before the next section heading or panel end fence.
    insert_pos = actions_section_start + 1
    for idx in range(actions_section_start + 1, panel_end):
        line = lines[idx].strip()
        if line.startswith("- ["):
            # This is a checkbox line; update insert position.
            insert_pos = idx + 1
        elif line.startswith("#") or "%%" in line:
            # Hit another section heading or fence; stop.
            break

    # Insert proposals at the determined position.
    for proposal in reversed(proposal_lines):
        lines.insert(insert_pos, proposal)

    return "\n".join(lines)


def _apply_note_writeback(
    state: PanelAgentState,
    original_note_text: str,
    vault_root: Path | None,
) -> None:
    """Remove executed checkboxes, write proposal suggestions, write receipts, and persist to vault file.

    This mirrors the writeback contract that ``handle_note_update`` applies in the
    non-watcher path, ensuring the documented panel contract (checkbox removal +
    AI status receipt block + proposal suggestions) is honoured for watcher/worker-driven execution.
    """
    executed_labels: list[str] = []
    proposed_labels: list[tuple[str, str]] = []  # (id, label) for proposed actions
    proposed_ids = set(state.proposed_action_ids or [])

    # Collect executed actions and proposed actions for writeback.
    executed_ids = set(state.executed_action_ids or [])
    for action in state.actions:
        if action.id in proposed_ids and not action.checked:
            # Proposed actions (injected catalog proposals) - write back as unchecked suggestions
            # Skip if this action was already executed in a previous run
            action_id_hash = stable_action_id(action.label)
            if action_id_hash not in executed_ids:
                proposed_labels.append((action.id, action.label))

    queued_labels: list[str] = []  # async actions (zone_move): queued, not yet executed
    fallback_labels: list[tuple[str, str]] = []  # (label, reason) for logged-but-not-triggered actions

    # Reasons that represent execution failures or mismatches we want to surface
    # as bounded fallback receipts (#980). Other "logged" outcomes (e.g. zone_move
    # routed through the action layer) are treated as queued, matching pre-#980
    # behavior.
    _FALLBACK_REASONS = {
        "unmapped_action",
        "unknown_mapping",
        "ambiguous_action",
        "watcher_not_allowed",
        "trust_verb_missing",
        "trust_verb_invalid",
        "admission_required",
    }

    for result in state.action_results:
        if result.checked and result.status in {"triggered", "logged"}:
            reason = str((result.details or {}).get("reason") or "")
            if result.status == "logged" and reason in _FALLBACK_REASONS:
                fallback_labels.append((result.label, reason))
            elif (result.intent_type or "").lower() == "zone_move":
                queued_labels.append(result.label)
            else:
                executed_labels.append(result.label)

    # Detect a no-match / no-op pass: this run produced no executed/queued/proposed
    # outcomes and the graph emitted a no_actions_matched signal. Surface a single
    # bounded receipt line so the human sees the decision in the AI status block.
    no_match_visible = (
        not executed_labels
        and not queued_labels
        and not proposed_labels
        and any(
            getattr(evt, "event", None) == "panel.action.logged"
            and (getattr(evt, "payload", {}) or {}).get("reason") == "no_actions_matched"
            for evt in (state.emitted_events or [])
        )
    )

    if (
        not executed_labels
        and not queued_labels
        and not proposed_labels
        and not fallback_labels
        and not no_match_visible
    ):
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

    # Suppress duplicate no-match receipt when instruction is unchanged (#1012).
    _instruction = state.panel.instruction or ""
    if no_match_visible and _has_no_match_marker(current_text, _instruction):
        no_match_visible = False

    # Filter fallback labels already visible in the current receipt block (#1012).
    fallback_labels = [
        (label, reason) for label, reason in fallback_labels
        if f"⚠️ {label} ({reason}," not in current_text
    ]

    # Early return if dedup eliminated all remaining work.
    if (
        not executed_labels
        and not queued_labels
        and not proposed_labels
        and not fallback_labels
        and not no_match_visible
    ):
        return

    # Annotate checkbox lines with ai:id so removal works correctly.
    annotated = annotate_action_ids(current_text)

    # Build the set of ai:id annotation IDs to remove, mapping from label -> stable hash.
    # Both synchronously executed and async-queued (zone_move) checkboxes are removed;
    # only their receipt text differs.
    ids_to_remove: set[str] = set()
    for label in executed_labels:
        ids_to_remove.add(stable_action_id(label))
    for label in queued_labels:
        ids_to_remove.add(stable_action_id(label))

    updated = remove_actions_from_markdown(annotated, ids_to_remove)

    # Write back proposed (unchecked) actions as suggestions for user confirmation.
    # Only labels that were newly inserted should trigger a fresh proposal receipt
    # so reruns over an already-proposed panel stay idempotent (#980 + #979).
    newly_proposed_labels: list[str] = []
    if proposed_labels:
        before_len = len(updated)
        # Compute newly-added labels by diffing the file before/after the insert,
        # but the simpler signal is the dedupe inside _write_proposals_to_panel:
        # detect which labels were not already in the panel block.
        existing_panel_labels = _existing_panel_proposal_labels(updated)
        newly_proposed_labels = [
            label for _id, label in proposed_labels
            if label.strip() not in existing_panel_labels
        ]
        updated = _write_proposals_to_panel(updated, proposed_labels)
        del before_len

    # Build receipt lines.
    # zone_move actions are asynchronous: the Vault Action Layer is the authoritative
    # execution receipt.  Write "queued" here so the panel receipt never claims completion.
    # Proposal receipts (#980) surface proposal-generation outcomes without claiming
    # execution; no-match receipts surface the runtime no-op decision.
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    receipts = [f"\u2705 {label} ({now_str})" for label in executed_labels]
    receipts += [f"\u23f3 {label} (queued, {now_str})" for label in queued_labels]
    # Proposal-offered receipts: visible suggestion line in AI status block.
    # Only emit for proposals that are newly inserted this pass; duplicate
    # proposals on rerun stay silent so receipt blocks remain bounded.
    receipts += [
        f"\U0001f4a1 F\u00f6rslag: {label} (v\u00e4ntar bekr\u00e4ftelse, {now_str})"
        for label in newly_proposed_labels
    ]
    # Fallback diagnostics: action was surfaced but did not execute.
    receipts += [
        f"\u26a0\ufe0f {label} ({reason}, {now_str})"
        for label, reason in fallback_labels
    ]
    # No-match / no-op receipt: one bounded line with an instruction-hash marker so
    # reruns over unchanged input are idempotent (#1012).
    if no_match_visible:
        _marker = _no_match_marker(state.panel.instruction or "")
        receipts.append(f"\u2139\ufe0f Inga \u00e5tg\u00e4rder matchade ({now_str}) {_marker}")

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

    # Persist executed/queued IDs so reruns are idempotent.
    all_done_labels = executed_labels + queued_labels
    upsert_executed_ids(note_uuid, [stable_action_id(label) for label in all_done_labels])

    # Refresh companion content_hash so it reflects the post-writeback content.
    _refresh_companion_hash(note_uuid, updated, vault_root, note_file)

    logger.info(
        "panel writeback applied note_path=%s removed=%d receipts=%d proposals=%d fallbacks=%d no_match=%s",
        note_file,
        len(ids_to_remove),
        len(receipts),
        len(proposed_labels),
        len(fallback_labels),
        no_match_visible,
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
