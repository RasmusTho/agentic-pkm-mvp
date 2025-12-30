from __future__ import annotations

import json
from typing import Any, Tuple

from langgraph.graph import END, START, StateGraph

from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import PanelActionCatalog, PanelActionDescriptor
from app.agents.panel_agent.settings import DeciderMode
from app.agents.panel_agent.state import PanelAgentState
from app.agents.panel_agent.wiring import get_default_action_wiring
from app.events.panel import (
    PanelActionLoggedEvent,
    PanelEventSource,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentExecutedEvent,
    PanelIntentExecutedPayload,
    PanelIntentPayload,
    PanelLogEntry,
    PanelLogEvent,
    PanelRuntimeActionResult,
)
from app.events.schema import OutboxEvent
from app.components.llm.fabric import get_chat_client
from app.components.llm.router import LLMTaskIntent

_IDEMPOTENCY_GUARD = IdempotencyGuard(ttl_seconds=86400.0)


def _build_panel_source() -> PanelEventSource:
    return PanelEventSource(trigger="runtime", component="panel_agent", sot="v5.0-runtime1")


def _build_action_result(
    action: PanelIntentAction,
    *,
    status: str,
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


def _promotion_event(intent_event: PanelIntentEvent, action: PanelIntentAction, *, target_event: str = "promote.intent.created") -> OutboxEvent:
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
        event=target_event,
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


def _handle_action(
    intent_event: PanelIntentEvent,
    action: PanelIntentAction,
    *,
    override_checked: bool | None = None,
    reason: str | None = None,
    action_wiring: dict[str, str] | None = None,
) -> Tuple[PanelRuntimeActionResult, list[Any]]:
    action_to_use = action
    if override_checked is not None:
        action_to_use = action.model_copy(update={"checked": override_checked})

    emitted: list[Any] = []
    emitted_names: list[str] = []
    if not action_to_use.checked:
        return _build_action_result(
            action_to_use, status="skipped", emitted=[], reason=reason or "unchecked"
        ), emitted

    note_id = intent_event.payload.note.uuid
    if action_to_use.id and _IDEMPOTENCY_GUARD.seen_action(note_id, action_to_use.id):
        return _build_action_result(
            action_to_use,
            status="skipped",
            emitted=[],
            reason=reason or "idempotent_duplicate",
        ), emitted

    mapping = action_to_use.mapping
    wiring = action_wiring or {}
    target_event = wiring.get(action_to_use.id)
    if mapping and (mapping.intent_type or "").lower() == "promotion":
        target = target_event or "promote.intent.created"
        promote_event = _promotion_event(intent_event, action_to_use, target_event=target)
        triggered_event = _action_triggered_event(intent_event, action_to_use, target_event=target)
        emitted.extend([promote_event, triggered_event])
        emitted_names.extend([promote_event.event, triggered_event.event])
        _IDEMPOTENCY_GUARD.mark_action(note_id, action_to_use.id)
        return _build_action_result(action_to_use, status="triggered", emitted=emitted_names), emitted

    logged_reason = reason or ("unhandled_action" if mapping else "unmapped_action")
    logged = _logged_event(intent_event, action_to_use, logged_reason)
    emitted.append(logged)
    emitted_names.append(logged.event)
    _IDEMPOTENCY_GUARD.mark_action(note_id, action_to_use.id)
    return (
        _build_action_result(
            action_to_use, status="logged", emitted=emitted_names, reason=logged.payload.get("reason")
        ),
        emitted,
    )


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


def _load_context(state: PanelAgentState) -> PanelAgentState:
    if state.intent_event is None:
        payload = PanelIntentPayload(note=state.note, panel=state.panel, actions=list(state.actions))
        state.intent_event = PanelIntentEvent(payload=payload)
    else:
        payload_actions = list(state.intent_event.payload.actions or [])
        if payload_actions != list(state.actions):
            payload = state.intent_event.payload.model_copy(update={"actions": list(state.actions)})
            state.intent_event = state.intent_event.model_copy(update={"payload": payload})
    if not state.trace_id and state.intent_event:
        state.trace_id = state.intent_event.trace_id
    if not state.action_catalog:
        state.action_catalog = PanelActionCatalog.from_descriptors([])
    if not state.action_wiring:
        state.action_wiring = dict(get_default_action_wiring())
    return state


def _available_actions_for_prompt(catalog: PanelActionCatalog) -> list[PanelActionDescriptor]:
    if catalog.actions:
        return catalog.actions
    return []


def _select_actions_llm(state: PanelAgentState) -> tuple[set[str], dict[str, str]] | None:
    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    actions = list(state.actions)
    if not actions:
        return set(), {}
    catalog = state.action_catalog or PanelActionCatalog.from_descriptors([])
    allowed_ids = {a.id for a in actions}
    available = [
        descriptor
        for descriptor in _available_actions_for_prompt(catalog)
        if descriptor.id in allowed_ids
    ]
    if not available:
        available = [
            PanelActionDescriptor(
                id=a.id,
                intent_type=a.mapping.intent_type if a.mapping else "",
                downstream_event="",
                labels=[a.label],
            )  # type: ignore[arg-type]
            for a in actions
        ]
    action_lines = []
    for descriptor in available:
        hint = descriptor.llm_hint or descriptor.description or descriptor.kind or descriptor.intent_type
        labels = ", ".join(descriptor.labels or [])
        action_lines.append(
            f"- id: {descriptor.id} | kind: {descriptor.kind or descriptor.intent_type} | labels: {labels} | hint: {hint}"
        )
    hint_lines = [f"- {a.label} (checked={a.checked})" for a in actions]
    system = " ".join(
        [
            "You are PanelAgent.",
            "Given the note context, panel instruction, checkbox hints, and available canonical actions,",
            "choose which actions to execute by returning JSON with an 'actions' array of objects",
            "with fields {id, reason?, message?}. Only use the provided action IDs. Do not invent new IDs.",
        ]
    )
    user_parts = [
        f"Instruction: {state.panel.instruction}",
        f"Note (snippet): {(state.note_content or '')[:800]}",
        "Checkbox hints:",
        *hint_lines,
        "Available actions (canonical):",
        *action_lines,
        "Return JSON like: {\"actions\": [{\"id\": \"promote.evergreen\", \"reason\": \"...\"}]}",
    ]
    pack = {"system": system, "user": "\n".join(user_parts)}
    try:
        client = get_chat_client(LLMTaskIntent(task_kind="decide", risk="high"))
        raw = client.chat("panel_agent.decider", pack, agent="panel_agent", kind="panel.decider", trace_id=state.trace_id)
        parsed = json.loads(raw or "{}")
        candidates = parsed.get("actions") if isinstance(parsed, dict) else parsed
        if candidates is None:
            candidates = parsed.get("chosen_actions") if isinstance(parsed, dict) else []
        if candidates is None:
            candidates = []
        selected: set[str] = set()
        reasons: dict[str, str] = {}
        valid_ids = {a.id for a in actions}

        if isinstance(candidates, list):
            for item in candidates:
                action_id: str | None = None
                reason: str | None = None
                if isinstance(item, str):
                    action_id = item
                elif isinstance(item, dict):
                    action_id = item.get("id") or item.get("action_id")
                    reason = item.get("reason") or item.get("why")
                if not action_id:
                    continue
                action_id = str(action_id).strip()
                if action_id not in valid_ids:
                    continue
                selected.add(action_id)
                if reason:
                    reasons[action_id] = reason
        # Empty set is a valid decision (LLM chose to run nothing).
        return selected, reasons
    except Exception:
        return None


def _apply_actions(state: PanelAgentState, *, selected_ids: set[str] | None, reasons: dict[str, str] | None = None) -> PanelAgentState:
    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    actions: list[PanelRuntimeActionResult] = []
    emitted: list[Any] = []

    executed_ids = {aid for aid in (state.executed_action_ids or []) if aid}
    allowed_ids = {action.id for action in state.actions}
    actions_to_process: list[PanelIntentAction] = [
        action for action in list(state.actions) if action.id not in executed_ids
    ]
    if selected_ids:
        selected_ids = {aid for aid in selected_ids if aid in allowed_ids and aid not in executed_ids}

    for action in actions_to_process:
        override_checked = None
        if selected_ids is not None:
            override_checked = action.id in selected_ids
        reason = reasons.get(action.id) if reasons else None
        result, new_events = _handle_action(
            state.intent_event, action, override_checked=override_checked, reason=reason, action_wiring=state.action_wiring
        )
        actions.append(result)
        emitted.extend(new_events)
    state.selected_action_ids = list(selected_ids or [])
    state.selected_action_reasons = reasons or {}
    state.action_results = actions
    state.emitted_events = emitted
    return state


def _decide_actions_llm_with_fallback(state: PanelAgentState) -> PanelAgentState:
    selection = _select_actions_llm(state)
    if selection is None:
        return _decide_actions_rule(state)
    chosen, reasons = selection
    return _apply_actions(state, selected_ids=chosen, reasons=reasons)


def _decide_actions_rule(state: PanelAgentState) -> PanelAgentState:
    return _apply_actions(state, selected_ids=None)


def _emit_events(state: PanelAgentState) -> PanelAgentState:
    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    executed_event = PanelIntentExecutedEvent(
        trace_id=state.intent_event.trace_id,
        source=_build_panel_source(),
        payload=PanelIntentExecutedPayload(note=state.note, panel=state.panel, actions=state.action_results),
    )

    log_entry = PanelLogEntry(
        trace_id=state.intent_event.trace_id,
        note=state.note,
        panel_id=state.panel.panel_id,
        summary=_build_summary(state.action_results),
        actions=state.action_results,
    )
    log_event = PanelLogEvent(trace_id=state.intent_event.trace_id, source=_build_panel_source(), payload=log_entry)

    emitted: list[Any] = [executed_event, *(state.emitted_events or []), log_event]
    state.emitted_events = emitted
    state.log_entry = log_entry
    return state


def build_panel_graph(decider_mode: DeciderMode = "rule"):
    graph = StateGraph(PanelAgentState)
    graph.add_node("load_context", _load_context)
    if decider_mode == "llm":
        graph.add_node("decide_actions", _decide_actions_llm_with_fallback)
    else:
        graph.add_node("decide_actions", _decide_actions_rule)
    graph.add_node("emit_events", _emit_events)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "decide_actions")
    graph.add_edge("decide_actions", "emit_events")
    graph.add_edge("emit_events", END)
    return graph.compile()


def run_panel_graph(state: PanelAgentState, decider_mode: DeciderMode = "rule"):
    compiled = build_panel_graph(decider_mode=decider_mode)
    result = compiled.invoke(state)
    if isinstance(result, PanelAgentState):
        return result
    try:
        return PanelAgentState.model_validate(result)
    except Exception:
        return state


__all__ = ["build_panel_graph", "run_panel_graph"]
