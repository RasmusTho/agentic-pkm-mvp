from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Tuple

from langgraph.graph import END, START, StateGraph

from app.domain.state_axes import build_promotion_transition
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import PanelActionCatalog, PanelActionDescriptor, normalize_label
from app.agents.panel_agent.settings import DeciderMode
from app.agents.panel_agent.state import PanelAgentState
from app.agents.panel_agent.wiring import get_default_action_wiring
from app.services.note_context import ContextBudget, NoteContext, NoteContextError, build_note_context
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
from app.components.reasoning import ReasoningTaskKind, get_reasoning_facade

_IDEMPOTENCY_GUARD = IdempotencyGuard(ttl_seconds=86400.0)

logger = logging.getLogger(__name__)

_PANEL_DECIDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["id"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["actions"],
    "additionalProperties": True,
}

PANEL_BUDGET = ContextBudget(
    max_body_chars=2000,
    include_relations=True,
    include_attachments=True,
    include_history=False,
)


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


def _available_actions_for_prompt(catalog: PanelActionCatalog) -> list[PanelActionDescriptor]:
    if catalog.actions:
        return catalog.actions
    return []


def _select_actions_from_instruction_hint(
    *,
    actions: list[PanelIntentAction],
    available: list[PanelActionDescriptor],
    instruction: str,
) -> tuple[set[str], dict[str, str]] | None:
    text = normalize_label(instruction)
    if not text:
        return None
    if any(
        phrase in text
        for phrase in (
            "do not promote",
            "don't promote",
            "dont promote",
            "not promote",
            "no promotion",
            "without promotion",
            "do not make this note evergreen",
            "don't make this note evergreen",
            "dont make this note evergreen",
            "do not make evergreen",
            "don't make evergreen",
            "dont make evergreen",
        )
    ):
        return None

    promotion_actions = [
        action
        for action in actions
        if action.mapping is not None and (action.mapping.intent_type or "").lower() == "promotion"
    ]
    if len(actions) != 1 or len(promotion_actions) != 1:
        return None

    action = promotion_actions[0]
    descriptor = next((item for item in available if item.id == action.id), None)
    labels = []
    if descriptor is not None:
        labels.extend(descriptor.labels or [])
        labels.extend(descriptor.aliases or [])
        if descriptor.description:
            labels.append(descriptor.description)
        if descriptor.llm_hint:
            labels.append(descriptor.llm_hint)
    labels.append(action.label)

    normalized_labels = [normalize_label(value) for value in labels if value]
    keyword_hit = any(keyword in text for keyword in ("promote", "promotion", "evergreen"))
    label_hit = any(label and (label in text or text in label) for label in normalized_labels)
    if not keyword_hit and not label_hit:
        return None
    return {action.id}, {action.id: "instruction_hint_fallback"}


def _resolve_vault_root(state: PanelAgentState) -> Path | None:
    """Return the vault root from state or VAULT_ROOT env var."""
    if state.vault_root is not None:
        return state.vault_root
    env = os.getenv("VAULT_ROOT")
    if env:
        return Path(env).expanduser()
    return None


def _build_note_snippet(state: PanelAgentState) -> str:
    """Build the note snippet for the LLM prompt.

    Tries NoteContext for a rich, structured view. Falls back to the legacy
    truncated ``note_content`` when NoteContext cannot be assembled.
    """
    vault_root = _resolve_vault_root(state)
    if vault_root is not None:
        try:
            ctx = build_note_context(
                uuid=state.note.uuid,
                vault_root=vault_root,
                budget=PANEL_BUDGET,
            )
            return _format_note_context(ctx)
        except (NoteContextError, Exception) as exc:  # noqa: BLE001
            logger.debug("NoteContext unavailable for %s, using snippet fallback: %s", state.note.uuid, exc)

    # Fallback: legacy truncated snippet
    return (state.note_content or "")[:800]


def _format_note_context(ctx: NoteContext) -> str:
    """Format a NoteContext into a prompt-friendly string."""
    parts: list[str] = []

    if ctx.frontmatter:
        fm_lines = [f"  {k}: {v}" for k, v in ctx.frontmatter.items()]
        parts.append("Frontmatter:\n" + "\n".join(fm_lines))

    if ctx.body:
        label = "Body (truncated):" if ctx.body_truncated else "Body:"
        parts.append(f"{label}\n{ctx.body}")

    if ctx.backlinks:
        parts.append("Backlinks:\n" + "\n".join(f"  - {bl}" for bl in ctx.backlinks))

    if ctx.attachments:
        att_lines = [f"  - {a.ref}" for a in ctx.attachments]
        parts.append("Attachments:\n" + "\n".join(att_lines))

    if ctx.outgoing_links:
        parts.append("Outgoing links:\n" + "\n".join(f"  - {ol}" for ol in ctx.outgoing_links))

    return "\n\n".join(parts) if parts else ""


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
        f"Note context:\n{_build_note_snippet(state)}",
        "Checkbox hints:",
        *hint_lines,
        "Available actions (canonical):",
        *action_lines,
        "Return JSON like: {\"actions\": [{\"id\": \"promote.evergreen\", \"reason\": \"...\"}]}",
    ]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
    try:
        facade = get_reasoning_facade()
        parsed = facade.structured(
            messages,
            schema=_PANEL_DECIDER_SCHEMA,
            task_kind=ReasoningTaskKind.DECIDE.llm_task_kind,
            trace_id=state.trace_id,
        )
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
        if not selected:
            hinted = _select_actions_from_instruction_hint(
                actions=actions,
                available=available,
                instruction=state.panel.instruction or "",
            )
            if hinted is not None:
                return hinted
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
        payload=PanelIntentExecutedPayload(
            note=state.note,
            panel=state.panel,
            actions=state.action_results,
            executed_action_ids=list(state.executed_action_ids or []),
        ),
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
