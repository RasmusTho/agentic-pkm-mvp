"""Engine-neutral cognition interface for PanelAgent action selection.

<!-- PA2-ENGINE-SEAM -->
This module defines the seam between the LangGraph execution surface and
concrete action-selection backends.  The ``PanelCognitionBackend`` Protocol
is the only contract the graph, parser, receipt, and event-emission paths
depend on.  Future backends (DeepAgents-style or otherwise) implement this
interface without requiring changes to those surfaces.

Current concrete backends:
- ``RuleCognitionBackend`` — respects checkbox state directly (default).
- ``LLMCognitionBackend``  — routes through the shared ``ReasoningFacade``
  with ``DECIDE`` task kind and falls back to rule mode on failure.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.agents.panel_agent.settings import DeciderMode
from app.agents.panel_agent.state import PanelAgentState
from app.components.reasoning import ReasoningTaskKind, get_reasoning_facade
from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    PanelActionDescriptor,
    normalize_label,
)
from app.events.panel import PanelIntentAction
from app.services.note_context import ContextBudget, NoteContext, NoteContextError, build_note_context

logger = logging.getLogger(__name__)

PANEL_BUDGET = ContextBudget(
    max_body_chars=2000,
    include_relations=True,
    include_attachments=True,
    include_history=False,
)

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


@runtime_checkable
class PanelCognitionBackend(Protocol):
    """Engine-neutral interface for panel action selection.

    Implementations receive the current ``PanelAgentState`` and return
    ``(selected_action_ids, reasons)`` to override checkbox-driven selection,
    or ``None`` to fall back to rule (checkbox-driven) mode.

    This seam keeps the LangGraph execution surface, parser, receipt, and
    emitted-event contracts independent from any concrete cognition backend.
    """

    def select_actions(
        self, state: PanelAgentState
    ) -> tuple[set[str], dict[str, str]] | None:
        """Select actions to execute.

        Returns:
            ``(selected_action_ids, reasons)`` if this backend has a selection.
            ``None`` to signal rule/checkbox-driven fallback.
        """
        ...


# ---------------------------------------------------------------------------
# Helpers used by LLMCognitionBackend
# ---------------------------------------------------------------------------


def _resolve_vault_root(state: PanelAgentState) -> Path | None:
    if state.vault_root is not None:
        return state.vault_root
    env = os.getenv("VAULT_ROOT")
    if env:
        return Path(env).expanduser()
    return None


def _format_note_context(ctx: NoteContext) -> str:
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


def _build_note_snippet(state: PanelAgentState) -> str:
    """Build the note snippet for the LLM prompt.

    Tries NoteContext for a rich, structured view.  Falls back to the legacy
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

    return (state.note_content or "")[:800]


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


def _select_actions_from_catalog(
    state: PanelAgentState,
    catalog: PanelActionCatalog,
) -> tuple[set[str], dict[str, str]] | None:
    """Freeform proposal path: derive candidate actions from instruction text + full catalog.

    Used when the panel has no checkbox actions. The LLM selects from the active catalog
    based on instruction text and catalog metadata (labels, llm_hint, description).
    Only canonical catalog IDs may be returned; out-of-catalog proposals are silently dropped.
    Returns None on LLM error so the caller can fall back to rule mode.
    """
    available = catalog.actions
    if not available:
        return set(), {}

    action_lines = []
    for descriptor in available:
        hint = descriptor.llm_hint or descriptor.description or descriptor.kind or descriptor.intent_type
        labels = ", ".join(descriptor.labels or [])
        action_lines.append(
            f"- id: {descriptor.id} | kind: {descriptor.kind or descriptor.intent_type} | labels: {labels} | hint: {hint}"
        )

    system = " ".join(
        [
            "You are PanelAgent.",
            "Given the note context, panel instruction, and available canonical actions,",
            "choose which actions to execute by returning JSON with an 'actions' array of objects",
            "with fields {id, reason?, message?}. Only use the provided action IDs. Do not invent new IDs.",
            "If no action fits the instruction, return an empty array.",
        ]
    )
    user_parts = [
        f"Instruction: {state.panel.instruction}",
        f"Note context:\n{_build_note_snippet(state)}",
        "Available actions (canonical):",
        *action_lines,
        'Return JSON like: {"actions": [{"id": "promote.evergreen", "reason": "..."}]}',
    ]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    valid_ids = {d.id for d in available}
    try:
        facade = get_reasoning_facade()
        parsed = facade.structured(
            messages,
            schema=_PANEL_DECIDER_SCHEMA,
            task_kind=ReasoningTaskKind.DECIDE.llm_task_kind,
            trace_id=state.trace_id,
        )
        candidates: list[object] = []
        if isinstance(parsed, dict):
            raw = parsed.get("actions")
            if raw is None:
                raw = parsed.get("chosen_actions")
            if isinstance(raw, list):
                candidates = raw

        selected: set[str] = set()
        reasons: dict[str, str] = {}
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
                logger.debug("Freeform proposal %r rejected: not in active catalog", action_id)
                continue
            selected.add(action_id)
            if reason:
                reasons[action_id] = reason
        return selected, reasons
    except Exception:
        return None


def _run_llm_selection(state: PanelAgentState) -> tuple[set[str], dict[str, str]] | None:
    """Core LLM-based action selection logic.

    Returns ``(selected_ids, reasons)`` or ``None`` if the LLM call fails.
    """
    assert state.intent_event is not None, "PanelAgentState must include intent_event"
    actions = list(state.actions)
    if not actions:
        # Freeform path: no checkbox actions — discover candidates from instruction + full catalog.
        catalog = state.action_catalog or PanelActionCatalog.from_descriptors([])
        return _select_actions_from_catalog(state, catalog)

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


# ---------------------------------------------------------------------------
# Concrete backends
# ---------------------------------------------------------------------------


class RuleCognitionBackend:
    """Rule-based cognition backend: respects checkbox state directly.

    Returns ``None`` to signal the graph should apply actions with
    checkbox-driven selection (no override).
    """

    def select_actions(
        self, state: PanelAgentState
    ) -> tuple[set[str], dict[str, str]] | None:
        return None


class LLMCognitionBackend:
    """LLM-based cognition backend: uses ``ReasoningFacade`` to select actions.

    Calls the shared ``ReasoningFacade`` with the ``DECIDE`` task kind and
    falls back to rule mode when the LLM call fails or returns nothing
    actionable.
    """

    def select_actions(
        self, state: PanelAgentState
    ) -> tuple[set[str], dict[str, str]] | None:
        return _run_llm_selection(state)


def _inject_catalog_proposals(state: PanelAgentState, proposed_ids: set[str]) -> PanelAgentState:
    """Inject catalog-derived PanelIntentAction objects for freeform proposals.

    Only injects actions that are not already present in state.actions.
    The injected actions carry the full mapping from the catalog descriptor so
    they flow through the same execution gates as checkbox-derived actions.
    """
    from app.events.panel import PanelIntentAction

    catalog = state.action_catalog or PanelActionCatalog.from_descriptors([])
    existing_ids = {action.id for action in state.actions}
    new_actions: list[PanelIntentAction] = []
    for action_id in proposed_ids:
        if action_id in existing_ids:
            continue
        descriptor = catalog.get(action_id)
        if descriptor is None:
            continue
        label = (descriptor.labels or [descriptor.id])[0]
        new_actions.append(
            PanelIntentAction(
                id=descriptor.id,
                label=label,
                checked=True,
                mapping=descriptor.to_mapping(),
            )
        )
    if not new_actions:
        return state
    return state.model_copy(update={"actions": list(state.actions) + new_actions})


def get_cognition_backend(mode: DeciderMode) -> PanelCognitionBackend:
    """Return the appropriate cognition backend for the given decider mode."""
    if mode == "llm":
        return LLMCognitionBackend()
    return RuleCognitionBackend()


__all__ = [
    "PanelCognitionBackend",
    "RuleCognitionBackend",
    "LLMCognitionBackend",
    "get_cognition_backend",
    "PANEL_BUDGET",
    "_build_note_snippet",
    "_format_note_context",
    "_inject_catalog_proposals",
]
