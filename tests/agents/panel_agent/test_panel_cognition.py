"""Tests for the PanelAgent engine-neutral cognition seam.

Verifies:
1. ``PanelCognitionBackend`` Protocol conformance — custom stubs satisfy it.
2. ``RuleCognitionBackend`` returns ``None`` (checkbox-driven fallback).
3. ``LLMCognitionBackend`` with a monkeypatched ``ReasoningFacade``.
4. ``run_panel_graph`` accepts an injected ``cognition_backend`` and routes
   through it without depending on a concrete LLM or LangGraph node layout.
"""
from __future__ import annotations

import pytest

from app.agents.panel_agent.cognition import (
    LLMCognitionBackend,
    PanelCognitionBackend,
    RuleCognitionBackend,
    get_cognition_backend,
)
from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import PanelActionCatalog
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)

TEST_NOTE_UUID = "cognition-test-00000000-0000-4000-8000-000000000001"
TEST_NOTE_PATH = "vault/CognitionTest.md"
TEST_NOTE_ORIGIN = "vault"


@pytest.fixture(autouse=True)
def _avoid_wiring_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.panel_agent.graph.get_default_action_wiring", lambda: {})


@pytest.fixture(autouse=True)
def _reset_idempotency_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.panel_agent.graph._IDEMPOTENCY_GUARD", IdempotencyGuard(ttl_seconds=86400.0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _intent_event_with_action(action: PanelIntentAction, *, trace_id: str = "trace-cognition") -> PanelIntentEvent:
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin=TEST_NOTE_ORIGIN)
    panel = PanelInfo(panel_id="panel-1", instruction="Promote please.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    return PanelIntentEvent(payload=payload, trace_id=trace_id)


def _state_from_intent(intent: PanelIntentEvent, catalog: PanelActionCatalog | None = None) -> PanelAgentState:
    return PanelAgentState(
        trace_id=intent.trace_id,
        note=intent.payload.note,
        panel=intent.payload.panel,
        actions=list(intent.payload.actions),
        intent_event=intent,
        action_catalog=catalog,
    )


def _promotion_action(*, checked: bool = True) -> PanelIntentAction:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    return PanelIntentAction(id=mapping.id, label="Promote", checked=checked, mapping=mapping)


# ---------------------------------------------------------------------------
# Stub backends
# ---------------------------------------------------------------------------


class _SelectingBackend:
    """Always selects the given action IDs."""

    def __init__(self, selected: set[str], reasons: dict[str, str] | None = None) -> None:
        self._selected = selected
        self._reasons = reasons or {}

    def select_actions(self, state: PanelAgentState) -> tuple[set[str], dict[str, str]] | None:
        return self._selected, self._reasons


class _PassthroughBackend:
    """Returns None — signals rule/checkbox-driven fallback."""

    def select_actions(self, state: PanelAgentState) -> tuple[set[str], dict[str, str]] | None:
        return None


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_selecting_backend_satisfies_protocol() -> None:
    assert isinstance(_SelectingBackend(set()), PanelCognitionBackend)


def test_passthrough_backend_satisfies_protocol() -> None:
    assert isinstance(_PassthroughBackend(), PanelCognitionBackend)


def test_rule_backend_satisfies_protocol() -> None:
    assert isinstance(RuleCognitionBackend(), PanelCognitionBackend)


def test_llm_backend_satisfies_protocol() -> None:
    assert isinstance(LLMCognitionBackend(), PanelCognitionBackend)


# ---------------------------------------------------------------------------
# RuleCognitionBackend
# ---------------------------------------------------------------------------


def test_rule_backend_returns_none() -> None:
    action = _promotion_action()
    intent = _intent_event_with_action(action)
    state = _state_from_intent(intent)
    assert RuleCognitionBackend().select_actions(state) is None


def test_get_cognition_backend_rule_returns_rule_backend() -> None:
    backend = get_cognition_backend("rule")
    assert isinstance(backend, RuleCognitionBackend)
    assert isinstance(backend, PanelCognitionBackend)


def test_get_cognition_backend_llm_returns_llm_backend() -> None:
    backend = get_cognition_backend("llm")
    assert isinstance(backend, LLMCognitionBackend)
    assert isinstance(backend, PanelCognitionBackend)


# ---------------------------------------------------------------------------
# LLMCognitionBackend with stub facade
# ---------------------------------------------------------------------------


class _StubReasoningFacade:
    def __init__(self, response: object) -> None:
        self._response = response

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None) -> object:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def test_llm_backend_selects_actions_via_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen", "reason": "facade selected"}]}),
    )
    action = _promotion_action()
    intent = _intent_event_with_action(action)
    state = _state_from_intent(intent)

    result = LLMCognitionBackend().select_actions(state)

    assert result is not None
    selected, reasons = result
    assert "promote.evergreen" in selected
    assert reasons.get("promote.evergreen") == "facade selected"


def test_llm_backend_returns_none_on_facade_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade(RuntimeError("facade down")),
    )
    action = _promotion_action()
    intent = _intent_event_with_action(action)
    state = _state_from_intent(intent)

    result = LLMCognitionBackend().select_actions(state)
    assert result is None


# ---------------------------------------------------------------------------
# Seam injection via run_panel_graph
# ---------------------------------------------------------------------------


def test_run_panel_graph_with_selecting_stub_triggers_action() -> None:
    action = _promotion_action()
    intent = _intent_event_with_action(action, trace_id="trace-selecting-stub")
    state = _state_from_intent(intent)

    stub = _SelectingBackend(selected={"promote.evergreen"})
    result = run_panel_graph(state, cognition_backend=stub)

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    assert "panel.action.triggered" in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"


def test_run_panel_graph_passthrough_backend_uses_checkbox_state() -> None:
    """Backend returning None falls back to checkbox-driven selection."""
    action = _promotion_action(checked=True)
    intent = _intent_event_with_action(action, trace_id="trace-passthrough")
    state = _state_from_intent(intent)

    result = run_panel_graph(state, cognition_backend=_PassthroughBackend())

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"


def test_run_panel_graph_selecting_stub_can_deselect_checked_action() -> None:
    """Backend returning empty set skips even a checked action."""
    action = _promotion_action(checked=True)
    intent = _intent_event_with_action(action, trace_id="trace-deselect")
    state = _state_from_intent(intent)

    result = run_panel_graph(state, cognition_backend=_SelectingBackend(selected=set()))

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "skipped"


def test_run_panel_graph_stub_backend_overrides_decider_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """When cognition_backend is provided, decider_mode is ignored."""
    called = []

    class _RecordingBackend:
        def select_actions(self, state: PanelAgentState) -> tuple[set[str], dict[str, str]] | None:
            called.append(True)
            return {"promote.evergreen"}, {}

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    action = _promotion_action()
    intent = _intent_event_with_action(action, trace_id="trace-override-mode")
    state = _state_from_intent(intent)

    result = run_panel_graph(state, decider_mode="llm", cognition_backend=_RecordingBackend())

    assert called, "stub backend was not called"
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
