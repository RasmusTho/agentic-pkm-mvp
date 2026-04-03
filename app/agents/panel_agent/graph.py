from __future__ import annotations

import logging
from typing import Any, Tuple

from langgraph.graph import END, START, StateGraph

from app.domain.state_axes import build_promotion_transition
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import PanelActionCatalog
from app.agents.panel_agent.cognition import PanelCognitionBackend, get_cognition_backend, _inject_catalog_proposals
from app.agents.panel_agent.settings import DeciderMode, get_panel_agent_decider
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

_IDEMPOTENCY_GUARD = IdempotencyGuard(ttl_seconds=86400.0)

logger = logging.getLogger(__name__)


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


def _execution_mode(state: PanelAgentState) -> str:
    raw = str(state.policy_flags.get("execution_mode") or "").strip().lower()
    if raw in {"manual", "watcher"}:
        return raw
    intent_event = getattr(state, "intent_event", None)
    trigger = str(getattr(getattr(intent_event, "source", None), "trigger", "") or "").strip().lower()
    if trigger == "watcher":
        return "watcher"
    return "manual"


def _action_resolution_reason(
    state: PanelAgentState,
    action: PanelIntentAction,
) -> str | None:
    catalog = state.action_catalog
    if not action.checked:
        return "unchecked"

    if catalog and catalog.has_ambiguous_label(action.label):
        return "ambiguous_action"

    mapping = action.mapping
    if mapping is None:
        return "unmapped_action"

    if catalog and catalog.actions and catalog.get(mapping.id) is None:
        return "unknown_mapping"

    mode = _execution_mode(state)
    if mode == "watcher" and catalog:
        descriptor = catalog.get(mapping.id)
        if descriptor and (descriptor.manual_only or not descriptor.watcher_allowed):
            return "watcher_not_allowed"

    return None


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
        payload["transition"] = build_promotion_transition(target_maturity=str(maturity))
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
    state: PanelAgentState,
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

    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    intent_event = state.intent_event
    note_id = intent_event.payload.note.uuid
    if action_to_use.id and _IDEMPOTENCY_GUARD.seen_action(note_id, action_to_use.id):
        return _build_action_result(
            action_to_use,
            status="skipped",
            emitted=[],
            reason=reason or "idempotent_duplicate",
        ), emitted

    mapping = action_to_use.mapping
    resolution_reason = _action_resolution_reason(state, action_to_use)
    wiring = action_wiring or {}
    target_event = wiring.get(action_to_use.id)
    if resolution_reason in {"ambiguous_action", "unmapped_action", "unknown_mapping", "watcher_not_allowed"}:
        logged = _logged_event(intent_event, action_to_use, resolution_reason)
        emitted.append(logged)
        emitted_names.append(logged.event)
        _IDEMPOTENCY_GUARD.mark_action(note_id, action_to_use.id)
        return (
            _build_action_result(
                action_to_use,
                status="logged",
                emitted=emitted_names,
                reason=logged.payload.get("reason"),
            ),
            emitted,
        )

    if mapping and (mapping.intent_type or "").lower() == "promotion":
        target = target_event or "promote.intent.created"
        promote_event = _promotion_event(intent_event, action_to_use, target_event=target)
        triggered_event = _action_triggered_event(intent_event, action_to_use, target_event=target)
        emitted.extend([promote_event, triggered_event])
        emitted_names.extend([promote_event.event, triggered_event.event])
        _IDEMPOTENCY_GUARD.mark_action(note_id, action_to_use.id)
        return _build_action_result(action_to_use, status="triggered", emitted=emitted_names), emitted

    logged_reason = reason or "unhandled_action"
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
            state,
            action,
            override_checked=override_checked,
            reason=reason,
            action_wiring=state.action_wiring,
        )
        actions.append(result)
        emitted.extend(new_events)
    handled_ids: set[str] = set()
    for result in actions:
        if result.status in {"triggered", "logged"}:
            handled_ids.add(result.id)
        elif result.status == "skipped" and result.details.get("reason") == "idempotent_duplicate":
            handled_ids.add(result.id)
    state.executed_action_ids = sorted(executed_ids | handled_ids)
    state.selected_action_ids = list(selected_ids or [])
    state.selected_action_reasons = reasons or {}
    state.action_results = actions
    state.emitted_events = emitted
    return state


def _decide_actions_with_backend(state: PanelAgentState, backend: PanelCognitionBackend) -> PanelAgentState:
    """Dispatch action selection through the engine-neutral cognition seam."""
    selection = backend.select_actions(state)
    if selection is None:
        return _apply_actions(state, selected_ids=None)
    chosen, reasons = selection
    # Freeform: inject catalog-derived PanelIntentAction objects for proposed IDs
    # that have no corresponding entry in state.actions (e.g., no-checkbox panels).
    if chosen:
        state = _inject_catalog_proposals(state, chosen)
    return _apply_actions(state, selected_ids=chosen, reasons=reasons)


def _emit_events(state: PanelAgentState) -> PanelAgentState:
    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    cognition_mode: str | None = state.decider_mode
    executed_event = PanelIntentExecutedEvent(
        trace_id=state.intent_event.trace_id,
        source=_build_panel_source(),
        payload=PanelIntentExecutedPayload(
            note=state.note,
            panel=state.panel,
            actions=state.action_results,
            executed_action_ids=list(state.executed_action_ids or []),
            cognition_mode=cognition_mode,
        ),
    )

    log_entry = PanelLogEntry(
        trace_id=state.intent_event.trace_id,
        note=state.note,
        panel_id=state.panel.panel_id,
        summary=_build_summary(state.action_results),
        actions=state.action_results,
        cognition_mode=cognition_mode,
    )
    log_event = PanelLogEvent(trace_id=state.intent_event.trace_id, source=_build_panel_source(), payload=log_entry)

    emitted: list[Any] = [executed_event, *(state.emitted_events or []), log_event]
    state.emitted_events = emitted
    state.log_entry = log_entry
    return state


def build_panel_graph(
    decider_mode: DeciderMode | None = None,
    cognition_backend: PanelCognitionBackend | None = None,
):
    """Build the PanelAgent LangGraph.

    Args:
        decider_mode: ``"llm"`` or ``"rule"``.  When ``None`` (default), the
            value is resolved from ``PANEL_AGENT_DECIDER`` (default ``"llm"``).
            ``"llm"`` is the runtime default for LLM-backed intent
            interpretation; ``"rule"`` is an explicit opt-out for unit tests,
            CI, and other bounded deterministic validation lanes.  Ignored when
            ``cognition_backend`` is provided explicitly.
        cognition_backend: Optional engine-neutral backend.  When supplied,
            ``decider_mode`` is ignored and the provided backend drives action
            selection.  Pass a stub or fake here in tests to exercise the
            execution path without depending on a concrete cognition
            implementation.
    """
    resolved_mode: DeciderMode = decider_mode if decider_mode is not None else get_panel_agent_decider()
    resolved_backend = cognition_backend if cognition_backend is not None else get_cognition_backend(resolved_mode)

    def _decide_actions(state: PanelAgentState) -> PanelAgentState:
        # Stamp the effective decider_mode into state so _emit_events can surface it.
        state = state.model_copy(update={"decider_mode": resolved_mode})
        return _decide_actions_with_backend(state, resolved_backend)

    graph = StateGraph(PanelAgentState)
    graph.add_node("load_context", _load_context)
    graph.add_node("decide_actions", _decide_actions)
    graph.add_node("emit_events", _emit_events)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "decide_actions")
    graph.add_edge("decide_actions", "emit_events")
    graph.add_edge("emit_events", END)
    return graph.compile()


def run_panel_graph(
    state: PanelAgentState,
    decider_mode: DeciderMode | None = None,
    cognition_backend: PanelCognitionBackend | None = None,
):
    """Run the PanelAgent graph and return the resulting state.

    Args:
        state: Initial ``PanelAgentState``.
        decider_mode: ``"llm"`` or ``"rule"``.  When ``None`` (default), the
            value is resolved from ``PANEL_AGENT_DECIDER`` (default ``"llm"``).
            ``"llm"`` is the runtime default for LLM-backed intent
            interpretation; ``"rule"`` is an explicit opt-out for tests and
            deterministic validation lanes.  Ignored when
            ``cognition_backend`` is provided.
        cognition_backend: Optional engine-neutral backend for action
            selection.  Useful for tests that need a deterministic or
            instrumented selection path.
    """
    compiled = build_panel_graph(decider_mode=decider_mode, cognition_backend=cognition_backend)
    result = compiled.invoke(state)
    if isinstance(result, PanelAgentState):
        return result
    try:
        return PanelAgentState.model_validate(result)
    except Exception:
        return state


__all__ = ["build_panel_graph", "run_panel_graph"]
