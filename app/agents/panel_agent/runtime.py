from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.events.panel import (
    NoteRef,
    PanelActionLoggedEvent,
    PanelEventSource,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentExecutedEvent,
    PanelIntentExecutedPayload,
    PanelLogEntry,
    PanelLogEvent,
    PanelRuntimeActionResult,
)
from app.events.schema import OutboxEvent
from app.outbox.events import INDEX_OUTBOX_PATH
from app.store.object_store import ObjectStore


def _resolve_outbox_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _write_outbox_events(outbox_path: Path, events: Iterable[Any]) -> None:
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        for event in events:
            if hasattr(event, "model_dump"):
                payload = event.model_dump(mode="json")
            elif isinstance(event, dict):
                payload = dict(event)
            else:
                continue
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _build_panel_source() -> PanelEventSource:
    return PanelEventSource(trigger="runtime", component="panel_agent", sot="v5.0-runtime1")


def _build_action_result(
    action: PanelIntentAction,
    *,
    status: Literal["triggered", "logged", "skipped"],
    emitted: list[str],
    reason: str | None = None,
) -> PanelRuntimeActionResult:
    details: dict[str, Any] = {}
    if reason:
        details["reason"] = reason
    return PanelRuntimeActionResult(
        id=action.id,
        label=action.label,
        checked=action.checked,
        status=status,  # type: ignore[arg-type]
        intent_type=action.mapping.intent_type if action.mapping else None,
        emitted_events=emitted,
        details=details,
    )


def _promotion_event(intent_event: PanelIntentEvent, action: PanelIntentAction) -> OutboxEvent:
    params = action.mapping.params if action.mapping else {}
    payload = {
        "note": intent_event.payload.note.model_dump(mode="json"),
        "panel": intent_event.payload.panel.model_dump(mode="json", exclude_none=True),
        "action": {
            "id": action.id,
            "label": action.label,
            "intent_type": action.mapping.intent_type if action.mapping else None,
            "downstream_event": action.mapping.downstream_event if action.mapping else None,
            "params": params,
        },
        "instruction": intent_event.payload.panel.instruction,
    }
    maturity = params.get("maturity")
    if maturity:
        payload["maturity"] = maturity
    return OutboxEvent(
        event="promote.intent.created",
        trace_id=intent_event.trace_id,
        source="panel_agent.runtime",
        payload=payload,
    )


def _action_triggered_event(intent_event: PanelIntentEvent, action: PanelIntentAction, target_event: str) -> OutboxEvent:
    return OutboxEvent(
        event="panel.action.triggered",
        trace_id=intent_event.trace_id,
        source="panel_agent.runtime",
        payload={
            "note": intent_event.payload.note.model_dump(mode="json"),
            "panel_id": intent_event.payload.panel.panel_id,
            "action": {"id": action.id, "label": action.label},
            "target_event": target_event,
        },
    )


def _logged_event(intent_event: PanelIntentEvent, action: PanelIntentAction, reason: str) -> PanelActionLoggedEvent:
    payload = {
        "note": intent_event.payload.note.model_dump(mode="json"),
        "panel_id": intent_event.payload.panel.panel_id,
        "action": {"id": action.id, "label": action.label, "checked": action.checked},
        "reason": reason,
    }
    if action.mapping:
        payload["mapping"] = action.mapping.model_dump(mode="json")
    return PanelActionLoggedEvent(trace_id=intent_event.trace_id, source=_build_panel_source(), payload=payload)


def _handle_action(intent_event: PanelIntentEvent, action: PanelIntentAction) -> Tuple[PanelRuntimeActionResult, list[Any]]:
    emitted: list[Any] = []
    emitted_names: list[str] = []
    if not action.checked:
        return _build_action_result(action, status="skipped", emitted=[], reason="unchecked"), emitted

    mapping = action.mapping
    if mapping and (mapping.intent_type or "").lower() == "promotion":
        promote_event = _promotion_event(intent_event, action)
        triggered_event = _action_triggered_event(intent_event, action, target_event="promote.intent.created")
        emitted.extend([promote_event, triggered_event])
        emitted_names.extend([promote_event.event, triggered_event.event])
        return _build_action_result(action, status="triggered", emitted=emitted_names), emitted

    logged = _logged_event(intent_event, action, "unhandled_action" if mapping else "unmapped_action")
    emitted.append(logged)
    emitted_names.append(logged.event)
    return _build_action_result(action, status="logged", emitted=emitted_names, reason=logged.payload.get("reason")), emitted


def _build_summary(actions: list[PanelRuntimeActionResult]) -> str:
    triggered = [a.label for a in actions if a.status == "triggered"]
    logged = [a.label for a in actions if a.status == "logged"]
    parts = ["panel.intent.executed"]
    if triggered:
        parts.append(f"triggered: {', '.join(triggered)}")
    if logged:
        parts.append(f"logged: {', '.join(logged)}")
    if not triggered and not logged:
        parts.append("no actions affected")
    return " | ".join(parts)


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
    resolved_outbox = _resolve_outbox_path(outbox_path)
    actions: list[PanelRuntimeActionResult] = []
    emitted: list[Any] = []

    for action in intent_event.payload.actions:
        result, new_events = _handle_action(intent_event, action)
        actions.append(result)
        emitted.extend(new_events)

    executed_event = PanelIntentExecutedEvent(
        trace_id=intent_event.trace_id,
        source=_build_panel_source(),
        payload=PanelIntentExecutedPayload(
            note=intent_event.payload.note,
            panel=intent_event.payload.panel,
            actions=actions,
        ),
    )
    emitted.insert(0, executed_event)

    log_entry = PanelLogEntry(
        trace_id=intent_event.trace_id,
        note=intent_event.payload.note,
        panel_id=intent_event.payload.panel.panel_id,
        summary=_build_summary(actions),
        actions=actions,
    )
    log_event = PanelLogEvent(trace_id=intent_event.trace_id, source=_build_panel_source(), payload=log_entry)
    emitted.append(log_event)

    _write_outbox_events(resolved_outbox, emitted)
    _persist_log(intent_event.payload.note, log_entry)

    return PanelRuntimeResult(intent=intent_event, actions=actions, emitted_events=emitted, log_entry=log_entry)


__all__ = ["execute_panel_intent", "PanelRuntimeResult"]
