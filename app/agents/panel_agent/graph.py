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
_TRUST_VERBS = {"ASSERT", "SUGGEST", "APPLY"}

# Governance-bearing capabilities (capability_class=governed_execution /
# authority_class=governed_effect per docs/CAPABILITY_CONTRACT_MODEL.md).
# Freeform LLM-proposed actions in this set must NOT be auto-executed in the
# same runtime pass — they must be written back as unchecked proposals and run
# only after explicit human confirmation on a subsequent pass.
#
# This hardcoded set is a transitional bridge: #982 will move capability_class
# / authority_class metadata onto each catalog entry so this gating becomes
# fully data-driven from the catalog descriptor.
_GOVERNANCE_BEARING_ACTION_IDS: frozenset[str] = frozenset({
    "promote.evergreen",
    "note.archive",
    "ingest.summary.create",
    "note.move.workbench",
})


def _is_governance_bearing(action: PanelIntentAction) -> bool:
    """Return True if the action's capability class is governance-bearing.

    A future revision will read `capability_class`/`authority_class` directly
    off the catalog descriptor (#982). Until that metadata lands, the explicit
    action-id allowlist above is the source of truth, augmented by a
    conservative fallback that treats any `promotion` intent_type as
    governance-bearing.
    """
    if action.id in _GOVERNANCE_BEARING_ACTION_IDS:
        return True
    mapping = action.mapping
    if mapping and (mapping.intent_type or "").strip().lower() == "promotion":
        return True
    return False


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

    # Mutation-capable actions must be explicitly trust-verb classified and admitted as APPLY.
    if (mapping.intent_type or "").strip().lower() == "promotion":
        trust_verb_raw = str(mapping.trust_verb or "").strip()
        if not trust_verb_raw:
            if not state.policy_flags.get("allow_legacy_promotion_without_trust_verb"):
                return "trust_verb_missing"
        else:
            trust_verb = trust_verb_raw.upper()
            if trust_verb not in _TRUST_VERBS:
                return "trust_verb_invalid"
            if trust_verb != "APPLY":
                return "admission_required"

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
    trust_verb = str(action.mapping.trust_verb or "").strip().upper() if action.mapping else ""
    payload = {
        "note": intent_event.payload.note.model_dump(mode="json"),
        "panel": intent_event.payload.panel.model_dump(mode="json", exclude_none=True),
        "action": {
            "id": action.id,
            "label": action.label,
            "intent_type": action.mapping.intent_type if action.mapping else None,
            "downstream_event": action.mapping.downstream_event if action.mapping else None,
            "trust_verb": trust_verb or None,
            "params": params,
        },
        "instruction": intent_event.payload.panel.instruction,
        "trust_verb": trust_verb or None,
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


def _logged_event(
    intent_event: PanelIntentEvent,
    action: PanelIntentAction,
    reason: str,
    *,
    cognition_metadata: dict[str, Any] | None = None,
) -> PanelActionLoggedEvent:
    payload = {
        "note": intent_event.payload.note.model_dump(mode="json"),
        "panel_id": intent_event.payload.panel.panel_id,
        "action": {"id": action.id, "label": action.label, "checked": action.checked},
        "reason": reason,
    }
    if action.mapping:
        payload["mapping"] = action.mapping.model_dump(mode="json")
    if cognition_metadata:
        # #984 attach bounded cognition-route observability so receipts surface
        # provider/model/fallback alongside the reason code.
        payload["cognition_metadata"] = dict(cognition_metadata)
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

    cognition_metadata = state.cognition_metadata or None
    emitted: list[Any] = []
    emitted_names: list[str] = []
    if not action_to_use.checked:
        # Freeform LLM proposal that was gated back to unchecked by the
        # proposal-vs-execution boundary (#979): emit a "proposal_offered"
        # signal so downstream consumers can see the proposal was surfaced
        # for human confirmation without executing.
        if reason == "proposal_offered":
            assert state.intent_event is not None
            logged = _logged_event(
                state.intent_event,
                action_to_use,
                "proposal_offered",
                cognition_metadata=cognition_metadata,
            )
            emitted.append(logged)
            return _build_action_result(
                action_to_use,
                status="skipped",
                emitted=[logged.event],
                reason="proposal_offered",
            ), emitted
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
    if resolution_reason in {
        "ambiguous_action",
        "unmapped_action",
        "unknown_mapping",
        "watcher_not_allowed",
        "trust_verb_missing",
        "trust_verb_invalid",
        "admission_required",
    }:
        logged = _logged_event(
            intent_event,
            action_to_use,
            resolution_reason,
            cognition_metadata=cognition_metadata,
        )
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
    logged = _logged_event(
        intent_event,
        action_to_use,
        logged_reason,
        cognition_metadata=cognition_metadata,
    )
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
    proposed_ids = {aid for aid in (state.proposed_action_ids or []) if aid}
    actions_to_process: list[PanelIntentAction] = [
        action for action in list(state.actions) if action.id not in executed_ids
    ]
    if selected_ids:
        selected_ids = {aid for aid in selected_ids if aid in allowed_ids and aid not in executed_ids}

    for action in actions_to_process:
        override_checked = None
        if selected_ids is not None:
            override_checked = action.id in selected_ids
            # Proposal vs execution boundary (#979):
            # An action that was injected as a freeform LLM proposal
            # (tracked in state.proposed_action_ids) was never explicitly
            # checked by the human. For governance-bearing capability
            # classes (governed_execution / governed_effect per
            # docs/CAPABILITY_CONTRACT_MODEL.md), we must NOT auto-check
            # it. It must be written back unchecked so the human confirms
            # on a subsequent pass. Non-governance-bearing proposals
            # (orientation / proposal / clarification / read-only) may
            # still execute in the same pass.
            # Block auto-execution when either:
            # - this-pass freeform proposal: action.id is in proposed_ids
            # - prior-pass proposal that survived writeback: action.proposal_pending
            #   (set by the parser from the persistent `<!--ai:proposed=...-->` marker)
            # Both gates require not action.checked: once the human toggles `[ ]` -> `[x]`,
            # the parsed action.checked is True and execution proceeds normally.
            gated_as_proposal = (
                override_checked
                and not action.checked
                and (action.id in proposed_ids or action.proposal_pending)
                and _is_governance_bearing(action)
            )
            if gated_as_proposal:
                override_checked = False
        else:
            gated_as_proposal = False
        reason = reasons.get(action.id) if reasons else None
        if gated_as_proposal:
            reason = "proposal_offered"
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

    # No-op / no-match visibility (#980): when this pass produced no executed,
    # logged, or proposed outcome, emit a bounded panel.action.logged event with
    # `reason: no_actions_matched` so the runtime decision stays visible. Only
    # surface this when the pass had genuine input to evaluate (panel actions or
    # a non-empty instruction triggering the freeform path); a converged rerun
    # whose only inputs were already-filtered executed IDs is not a no-match.
    proposed_ids_now = {aid for aid in (state.proposed_action_ids or []) if aid}
    produced_any = any(
        r.status in {"triggered", "logged"}
        or (r.status == "skipped" and r.details.get("reason") == "proposal_offered")
        for r in actions
    )
    instruction_text = ""
    try:
        instruction_text = (state.intent_event.payload.panel.instruction or "").strip()
    except Exception:
        instruction_text = ""
    # Converged-rerun signal: either the runtime flagged this pass as a
    # post-execution rerun, or prior executed IDs are present with no fresh
    # checkbox input. Treat as already-finished, not no-match.
    converged_rerun = state.converged_rerun or (
        bool(state.executed_action_ids) and not actions_to_process
    )
    # Only emit no-match when there was real input AND a cognition decision was
    # made this pass (freeform LLM returned empty, or checked-but-unmapped). A
    # rule-mode passthrough with empty actions is not a no-match.
    cognition_decided = bool(state.cognition_decision_made)
    had_input = (
        bool(actions_to_process)
        or (bool(instruction_text) and cognition_decided)
    ) and not converged_rerun
    if had_input and not produced_any and not proposed_ids_now:
        intent_event = state.intent_event
        instruction = ""
        try:
            instruction = (intent_event.payload.panel.instruction or "").strip()
        except Exception:
            instruction = ""
        no_match_payload: dict[str, Any] = {
            "note": intent_event.payload.note.model_dump(mode="json"),
            "panel_id": intent_event.payload.panel.panel_id,
            "action": None,
            "reason": "no_actions_matched",
            "instruction": instruction,
        }
        if state.cognition_metadata:
            no_match_payload["cognition_metadata"] = dict(state.cognition_metadata)
        no_match_event = PanelActionLoggedEvent(
            trace_id=intent_event.trace_id,
            source=_build_panel_source(),
            payload=no_match_payload,
        )
        emitted.append(no_match_event)

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
    # Mark that a cognition decision was made (even if empty) so the no-match
    # receipt path (#980) can distinguish freeform decide=nothing from rule-mode
    # passthrough.
    state.cognition_decision_made = True
    return _apply_actions(state, selected_ids=chosen, reasons=reasons)


def _emit_events(state: PanelAgentState) -> PanelAgentState:
    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    cognition_mode: str | None = state.decider_mode
    cognition_metadata = dict(state.cognition_metadata or {})
    executed_event = PanelIntentExecutedEvent(
        trace_id=state.intent_event.trace_id,
        source=_build_panel_source(),
        payload=PanelIntentExecutedPayload(
            note=state.note,
            panel=state.panel,
            actions=state.action_results,
            executed_action_ids=list(state.executed_action_ids or []),
            cognition_mode=cognition_mode,
            cognition_metadata=cognition_metadata,
        ),
    )

    log_entry = PanelLogEntry(
        trace_id=state.intent_event.trace_id,
        note=state.note,
        panel_id=state.panel.panel_id,
        summary=_build_summary(state.action_results),
        actions=state.action_results,
        cognition_mode=cognition_mode,
        cognition_metadata=cognition_metadata,
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
